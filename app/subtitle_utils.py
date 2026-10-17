"""Speech-to-text (faster-whisper) -> SRT, and burning an existing
subtitle file onto a video (see ffmpeg_utils.burn_subtitles for the burn
step itself).
"""

from __future__ import annotations

from pathlib import Path

from app.ffmpeg_utils import probe_duration_sec, resolve_ffprobe

WHISPER_MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]


def format_srt_timestamp(total_seconds: float) -> str:
    millis_total = round(total_seconds * 1000)
    hours, remainder = divmod(millis_total, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def transcribe_to_srt(
    video_path: Path,
    *,
    model_size: str = "small",
    translate_to_english: bool = True,
    on_progress=None,
) -> str:
    """Runs on whatever thread calls it — a Qt worker should re-emit
    `on_progress` as a signal rather than touching widgets from here.

    faster-whisper reads audio straight out of the video container (no
    separate extraction step needed). The model downloads from Hugging
    Face on first use for a given size (cached under the user's home
    directory afterward) — needs internet the first time only.
    """
    from faster_whisper import WhisperModel

    def report(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(pct, msg)

    report(2, f"Loading Whisper model ({model_size})...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    ffprobe = resolve_ffprobe()
    total_duration = probe_duration_sec(ffprobe, video_path) if ffprobe else None

    report(5, "Transcribing audio...")
    segments, info = model.transcribe(
        str(video_path),
        task="translate" if translate_to_english else "transcribe",
        beam_size=5,
        vad_filter=True,
    )

    duration = total_duration or info.duration or 1.0

    lines: list[str] = []
    index = 1
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        lines.append(
            f"{index}\n{format_srt_timestamp(segment.start)} --> {format_srt_timestamp(segment.end)}\n{text}\n"
        )
        index += 1
        pct = 5 + int(90 * min(segment.end / duration, 1.0))
        report(pct, f"Transcribing... {segment.end:.0f}s / {duration:.0f}s")

    report(100, f"Done — {index - 1} line(s).")
    return "\n".join(lines)
