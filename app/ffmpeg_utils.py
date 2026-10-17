"""FFmpeg discovery and the video-joining pipeline.

Two-tier join strategy:
1. Fast path: concat demuxer with `-c copy` (no re-encode). Works instantly
   when every input already shares a compatible codec/container — the
   common case when all clips come from the same camera/app.
2. Robust fallback: if the fast path fails (mismatched codecs/resolutions),
   normalize every clip to a uniform H.264/AAC stream first (muxing silent
   audio into clips that have none, so every clip ends up with exactly one
   video + one audio stream), then concat those with the same fast demuxer.
   This mirrors the approach that's actually necessary once inputs can
   differ, rather than trying to guess compatibility up front.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path

_TIMEOUT_SEC = 1800


def resolve_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def resolve_ffprobe() -> str | None:
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = resolve_ffmpeg()
    if ffmpeg:
        candidate = Path(ffmpeg).with_name(
            "ffprobe.exe" if Path(ffmpeg).suffix.lower() == ".exe" else "ffprobe"
        )
        if candidate.exists():
            return str(candidate)
    return None


class FfmpegError(Exception):
    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


def probe_duration_sec(ffprobe: str, video_path: Path) -> float | None:
    try:
        result = _run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(video_path),
            ]
        )
        return float(result.stdout.decode("utf-8", errors="replace").strip())
    except Exception:
        return None


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT_SEC, check=False)


def has_audio_stream(ffprobe: str, video_path: Path) -> bool:
    try:
        result = _run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                str(video_path),
            ]
        )
        return bool(result.stdout.decode("utf-8", errors="replace").strip())
    except Exception:
        return False


def _probe_signature(ffprobe: str, video_path: Path) -> tuple | None:
    """A tuple describing the video's codec/resolution/audio-codec, used to
    decide whether stream-copy concat is actually safe.

    This matters because ffmpeg's concat demuxer with `-c copy` can exit 0
    while silently producing a corrupted or wrong-duration file when inputs
    have mismatched resolutions or codecs — it just remuxes packets without
    validating that they're consistent. Checking compatibility up front
    with ffprobe, rather than trusting ffmpeg's return code, is the only
    reliable way to know the fast path is actually safe to use.
    """
    try:
        result = _run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,pix_fmt,avg_frame_rate",
                "-of", "csv=p=0",
                str(video_path),
            ]
        )
        video_sig = result.stdout.decode("utf-8", errors="replace").strip()
        if not video_sig:
            return None

        audio_result = _run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=codec_name,sample_rate,channels",
                "-of", "csv=p=0",
                str(video_path),
            ]
        )
        audio_sig = audio_result.stdout.decode("utf-8", errors="replace").strip()
        return (video_sig, audio_sig)
    except Exception:
        return None


def clips_are_copy_compatible(ffprobe: str, paths: list[Path]) -> bool:
    signatures = [_probe_signature(ffprobe, p) for p in paths]
    if any(sig is None for sig in signatures):
        return False
    return len(set(signatures)) == 1


def _parse_frame_rate(raw: str) -> float | None:
    # ffprobe reports frame rate as "num/den", e.g. "24/1" or "30000/1001".
    try:
        num, _, den = raw.partition("/")
        den_val = float(den) if den else 1.0
        return float(num) / den_val if den_val else None
    except (ValueError, ZeroDivisionError):
        return None


def probe_target_dimensions(ffprobe: str, video_path: Path) -> tuple[int, int, float] | None:
    """(width, height, fps) of the reference clip normalization targets
    every other clip to — matching resolution AND frame rate matters even
    after matching codec, since the concat demuxer's `-c copy` step relies
    on genuinely uniform stream parameters, not just "same codec name"."""
    try:
        result = _run(
            [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate",
                "-of", "csv=p=0",
                str(video_path),
            ]
        )
        parts = result.stdout.decode("utf-8", errors="replace").strip().split(",")
        if len(parts) < 4:
            return None
        width, height = int(parts[0]), int(parts[1])
        fps = _parse_frame_rate(parts[2]) or _parse_frame_rate(parts[3]) or 30.0
        return (width, height, fps)
    except Exception:
        return None


def _escape_concat_path(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def _write_concat_list(paths: list[Path], list_file: Path) -> None:
    list_file.write_text(
        "\n".join(f"file '{_escape_concat_path(p)}'" for p in paths), encoding="utf-8"
    )


def _concat_copy(ffmpeg: str, paths: list[Path], out_path: Path, tmp_dir: Path) -> None:
    list_file = tmp_dir / "concat_list.txt"
    _write_concat_list(paths, list_file)
    result = _run(
        [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            "-loglevel", "error",
            str(out_path),
        ]
    )
    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise FfmpegError("Fast concat failed", result.stderr.decode("utf-8", errors="replace"))


def _normalize_clip(
    ffmpeg: str,
    ffprobe: str | None,
    video_path: Path,
    out_path: Path,
    target: tuple[int, int, float] | None,
) -> None:
    # Matching codec alone isn't enough for a safe `-c copy` concat
    # afterwards — every clip also needs the SAME resolution and frame
    # rate, or the concat demuxer can silently produce a file with wrong
    # duration/timestamps (frames are all there, but PTS math breaks).
    # `pad` after `scale` letterboxes instead of distorting aspect ratio.
    video_filter = None
    if target is not None:
        width, height, fps = target
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
        )

    video_args = ["-vf", video_filter] if video_filter else []

    # No ffprobe to check with -> assume silent rather than guessing wrong
    # in a way ffmpeg would hard-fail on (mapping a nonexistent audio
    # stream). Rare in practice: ffprobe ships alongside ffmpeg in nearly
    # every distribution.
    if ffprobe and has_audio_stream(ffprobe, video_path):
        cmd = [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-map", "0:v:0", "-map", "0:a:0",
            *video_args,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-loglevel", "error",
            str(out_path),
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-i", str(video_path),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v:0", "-map", "1:a",
            *video_args,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            "-loglevel", "error",
            str(out_path),
        ]
    result = _run(cmd)
    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise FfmpegError(
            f"Failed to normalize {video_path.name}", result.stderr.decode("utf-8", errors="replace")
        )


def join_videos(
    paths: list[Path],
    out_path: Path,
    tmp_dir: Path,
    *,
    on_progress=None,
) -> None:
    """Raises FfmpegError on failure. `on_progress(percent, message)` is
    called from whatever thread this runs on — callers on a Qt worker
    thread should re-emit it as a signal rather than touching widgets here.
    """
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise FfmpegError("FFmpeg was not found on PATH and the imageio-ffmpeg fallback is not installed.")

    def report(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(pct, msg)

    ffprobe = resolve_ffprobe()
    if ffprobe and clips_are_copy_compatible(ffprobe, paths):
        report(5, "Clips match — joining without re-encoding...")
        _concat_copy(ffmpeg, paths, out_path, tmp_dir)
        report(100, "Done (fast join).")
        return

    if not ffprobe:
        report(5, "ffprobe unavailable — re-encoding to be safe...")
    else:
        report(5, "Clips differ in format — normalizing each clip...")

    target = probe_target_dimensions(ffprobe, paths[0]) if ffprobe else None

    normalized: list[Path] = []
    total = len(paths)
    for i, path in enumerate(paths):
        pct = 10 + int(60 * (i / max(total, 1)))
        report(pct, f"Normalizing clip {i + 1}/{total}: {path.name}")
        out = tmp_dir / f"norm_{i:03d}.mp4"
        _normalize_clip(ffmpeg, ffprobe, path, out, target)
        normalized.append(out)

    report(80, "Joining normalized clips...")
    _concat_copy(ffmpeg, normalized, out_path, tmp_dir)
    report(100, "Done.")


def burn_subtitles(subtitle_path: Path, video_path: Path, out_path: Path) -> None:
    """Hardcodes `subtitle_path` (.srt or .ass — ffmpeg's `subtitles` filter
    renders both via libass, so styled/karaoke .ass files keep their
    styling) onto `video_path`'s picture. Re-encodes video (burning text in
    is a pixel operation); audio is stream-copied since it's untouched.

    Runs ffmpeg with `cwd` set to the subtitle file's own directory and
    passes just its filename to the filter — the `subtitles=` filter graph
    parses `:` as an option separator, so an absolute Windows path
    (`C:\\...`) breaks it; this sidesteps that instead of trying to escape it.
    """
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise FfmpegError("FFmpeg was not found on PATH and the imageio-ffmpeg fallback is not installed.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-vf", f"subtitles={subtitle_path.name}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-loglevel", "error",
        str(out_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, timeout=_TIMEOUT_SEC, check=False, cwd=subtitle_path.parent
    )
    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise FfmpegError("Burning subtitles failed", result.stderr.decode("utf-8", errors="replace"))


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?:\s*(Video|Audio):")


def media_duration_sec(path: Path) -> float | None:
    """Length in seconds. Uses ffprobe when it is installed, otherwise parses
    `ffmpeg -i` (the frozen app often has only the imageio-ffmpeg binary)."""
    ffprobe = resolve_ffprobe()
    if ffprobe:
        probed = probe_duration_sec(ffprobe, path)
        if probed is not None and probed > 0:
            return probed
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return None
    text = _ffmpeg_banner(ffmpeg, path)
    match = _DURATION_RE.search(text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return duration if duration > 0 else None


def _ffmpeg_banner(ffmpeg: str, path: Path) -> str:
    # `ffmpeg -i` exits 1 because there is no output file. The banner on
    # stderr is still the info we need.
    result = _run([ffmpeg, "-hide_banner", "-i", str(path)])
    return result.stderr.decode("utf-8", errors="replace")


def _has_stream(ffmpeg: str, path: Path, kind: str) -> bool:
    text = _ffmpeg_banner(ffmpeg, path)
    return any(found == kind for found in _STREAM_RE.findall(text))


def attach_audio(video_path: Path, audio_path: Path, out_path: Path, *, on_progress=None) -> None:
    """Replace the video's audio with `audio_path`.

    When the music is shorter than the picture, it is concatenated with
    itself (`-stream_loop`) until the output lasts exactly as long as the
    video. When the music is longer, it is trimmed to the video.
    """
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise FfmpegError("FFmpeg was not found on PATH and the imageio-ffmpeg fallback is not installed.")
    if not video_path.is_file():
        raise FfmpegError(f"Video not found: {video_path}")
    if not audio_path.is_file():
        raise FfmpegError(f"Audio not found: {audio_path}")
    if video_path.resolve() == out_path.resolve():
        raise FfmpegError("Choose an output file that is different from the source video.")

    def report(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(pct, msg)

    report(5, "Reading the video and the music...")
    if not _has_stream(ffmpeg, video_path, "Video"):
        raise FfmpegError("That file has no video stream.")
    if not _has_stream(ffmpeg, audio_path, "Audio"):
        raise FfmpegError("That file has no audio stream.")

    video_duration = media_duration_sec(video_path)
    audio_duration = media_duration_sec(audio_path)
    if audio_duration is not None and video_duration is not None and audio_duration + 0.05 < video_duration:
        repeats = max(1, math.ceil(video_duration / audio_duration))
        report(
            15,
            f"Music is {audio_duration:.1f}s and the video is {video_duration:.1f}s — "
            f"repeating the music back-to-back ({repeats} times) to fill the video.",
        )
    elif audio_duration is not None and video_duration is not None and audio_duration > video_duration + 0.05:
        report(15, f"Music is longer than the video — trimming it to {video_duration:.1f}s.")
    else:
        report(15, "Attaching the music...")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    report(30, "Writing the video...")
    copied = _mux_audio(ffmpeg, video_path, audio_path, out_path, video_duration, reencode_video=False)
    if copied.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        if out_path.exists():
            out_path.unlink()
        report(45, "The video codec can't be copied — re-encoding the picture...")
        encoded = _mux_audio(ffmpeg, video_path, audio_path, out_path, video_duration, reencode_video=True)
        if encoded.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            detail = encoded.stderr.decode("utf-8", errors="replace") or copied.stderr.decode("utf-8", errors="replace")
            raise FfmpegError("Attaching the music failed", detail)

    report(100, "Done.")


def _mux_audio(
    ffmpeg: str,
    video_path: Path,
    audio_path: Path,
    out_path: Path,
    video_duration: float | None,
    *,
    reencode_video: bool,
) -> subprocess.CompletedProcess:
    # -stream_loop repeats the whole music file. -t / -shortest stop at the
    # video's length, so a short track is tiled and a long track is cut.
    cmd = [
        ffmpeg, "-y",
        "-i", str(video_path),
        "-stream_loop", "-1",
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
    ]
    if reencode_video:
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    if video_duration is not None and video_duration > 0:
        cmd += ["-t", f"{video_duration:.3f}"]
    cmd += ["-movflags", "+faststart", "-loglevel", "error", str(out_path)]
    return _run(cmd)
