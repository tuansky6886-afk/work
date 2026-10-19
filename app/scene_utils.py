"""Split a video into 15-second scenes and render one reconstruction prompt.

Pure functions only. Network calls live in scene_scan.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCENE_SECONDS = 15
# Scene Prompts never spends more than this many scene calls on one video.
MAX_SCENE_PROMPTS = 20

_CONSTRAINT = (
    "natural physics, consistent facial features and outfit, no morphing, "
    "no extra fingers, no text overlay, no watermark."
)
_SECTION = re.compile(
    r"(?im)^\s*(?:\d+[.)]\s*)?(?:\*\*|__)?(VISUAL|KEYFRAME|VIDEO)(?:\*\*|__)?\s*:\s*(?:\*\*|__)?"
)
_ASPECTS = (
    (16 / 9, "16:9"),
    (3 / 2, "3:2"),
    (4 / 3, "4:3"),
    (1.0, "1:1"),
    (3 / 4, "3:4"),
    (2 / 3, "2:3"),
    (9 / 16, "9:16"),
)


class SceneScanError(Exception):
    """A failure we can show to the user as-is."""


@dataclass(frozen=True)
class SceneWindow:
    index: int
    start: int
    end: int

    @property
    def duration(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class SceneDraft:
    window: SceneWindow
    visual: str
    speech: str
    keyframe: str
    video_prompt: str


@dataclass(frozen=True)
class ScanOutput:
    text: str
    title: str
    stopped: bool
    finished_scenes: int
    planned_scenes: int


@dataclass(frozen=True)
class ScenePlan:
    windows: tuple[SceneWindow, ...]
    remainder: int
    capped: bool


def plan_scenes(duration_seconds: int) -> ScenePlan:
    """Return full 15-second windows, the unused tail, and whether the cap applied.

    A video shorter than 15 seconds becomes one scene of its real length.
    A longer video drops a tail shorter than one scene instead of stretching
    the last scene. More than MAX_SCENE_PROMPTS full scenes keeps only the
    first ones; `remainder` is then every second after that cut, and
    `capped` is True.
    """
    if duration_seconds <= 0:
        raise SceneScanError("This video has no fixed length, so it can't be split into 15-second scenes.")
    if duration_seconds < SCENE_SECONDS:
        return ScenePlan((SceneWindow(1, 0, duration_seconds),), 0, False)
    full_count = duration_seconds // SCENE_SECONDS
    tail = duration_seconds - full_count * SCENE_SECONDS
    count = min(full_count, MAX_SCENE_PROMPTS)
    windows = tuple(
        SceneWindow(index=i + 1, start=i * SCENE_SECONDS, end=(i + 1) * SCENE_SECONDS)
        for i in range(count)
    )
    capped = full_count > MAX_SCENE_PROMPTS
    remainder = duration_seconds - count * SCENE_SECONDS if capped else tail
    return ScenePlan(windows, remainder, capped)


def speech_for_window(snippets: tuple[tuple[float, str], ...] | list[tuple[float, str]], start: int, end: int) -> str:
    """Join caption cues whose start time falls inside [start, end)."""
    parts: list[str] = []
    for cue_start, text in snippets:
        if start <= cue_start < end:
            collapsed = " ".join(text.split())
            if collapsed:
                parts.append(collapsed)
    return " ".join(parts)


def aspect_ratio_label(width: int, height: int) -> str:
    """Pick the nearest Grok aspect ratio for a frame size."""
    if width <= 0 or height <= 0:
        return "16:9"
    ratio = width / height
    return min(_ASPECTS, key=lambda item: abs(item[0] - ratio))[1]


def resolve_aspect(width: int | None, height: int | None, override: str | None) -> tuple[str, str]:
    """Return (aspect label, where it came from)."""
    if override in {label for _ratio, label in _ASPECTS}:
        return override, "chosen"
    if width and height:
        return aspect_ratio_label(width, height), "from the video"
    return "16:9", "default"


def parse_scene_response(text: str) -> tuple[str, str, str]:
    """Pull VISUAL, KEYFRAME, and VIDEO out of a model reply.

    Labels may be wrapped in markdown or numbered. Text before the first
    label is ignored. A reply with no labels is kept as the visual.
    """
    body = _strip_fences(text)
    matches = list(_SECTION.finditer(body))
    if not matches:
        return body.strip(), "(missing)", "(missing)"

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1).upper()] = body[match.end():block_end].strip()

    visual = " ".join(sections.get("VISUAL", "").split())
    keyframe = sections.get("KEYFRAME", "").strip() or "(missing)"
    video = sections.get("VIDEO", "").strip() or "(missing)"
    if not visual:
        visual = "(The model returned no description for this scene.)"
    return visual, keyframe, video


def render_document(
    *,
    title: str,
    video_id: str,
    duration_seconds: int,
    width: int | None,
    height: int | None,
    aspect: str,
    aspect_source: str,
    bible: str,
    drafts: list[SceneDraft],
    planned_count: int,
    remainder: int,
    caption_note: str,
    stopped: bool,
    capped: bool = False,
) -> str:
    """One copyable prompt: locked look, then every finished scene."""
    lines: list[str] = [
        title or "YouTube video",
        f"Source: https://www.youtube.com/watch?v={video_id}",
        f"Duration: {format_clock(duration_seconds)}",
        _scene_count_line(duration_seconds, planned_count, remainder, capped=capped),
        _frame_line(width, height, aspect, aspect_source),
        caption_note,
        "",
        "Render each GROK VIDEO PROMPT as its own Image-to-Video clip, then join the clips in order.",
        "Use the keyframe as the first frame so the face and the place stay locked.",
    ]
    if stopped:
        lines.append("Stopped early. Only the scenes finished before the scan was cancelled are below.")
    lines.extend(["", "CHARACTER & WORLD (paste into every keyframe):", bible.strip() or "(missing)", ""])

    number_width = max(2, len(str(planned_count or 1)))
    for draft in drafts:
        lines.append(_render_scene(draft, aspect, number_width))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_clock(seconds: int) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def bible_sample_fps(duration_seconds: int) -> float:
    """About 120 frames across the whole video, never above 1 fps."""
    if duration_seconds <= 0:
        return 1.0
    return max(0.1, min(1.0, round(120 / duration_seconds, 2)))


def _scene_count_line(duration_seconds: int, planned_count: int, remainder: int, *, capped: bool) -> str:
    if planned_count == 1 and duration_seconds < SCENE_SECONDS:
        return f"Scenes: 1 scene of {duration_seconds}s (shorter than 15 seconds)"
    line = f"Scenes: {planned_count} x 15s"
    if capped:
        covered = planned_count * SCENE_SECONDS
        line += (
            f" — only the first {format_clock(covered)} of {format_clock(duration_seconds)} "
            f"is scanned (max {MAX_SCENE_PROMPTS} scenes)"
        )
        return line
    if remainder:
        line += f" — the last {remainder}s are shorter than one scene and are left out"
    return line


def _frame_line(width: int | None, height: int | None, aspect: str, aspect_source: str) -> str:
    if width and height:
        return f"Frame: {width}x{height}. Aspect ratio: {aspect} ({aspect_source})."
    return f"Aspect ratio: {aspect} ({aspect_source})."


def _render_scene(draft: SceneDraft, aspect: str, number_width: int) -> str:
    window = draft.window
    speech = draft.speech.strip() or "[Không lời — nhạc nền]"
    video_prompt = _with_constraint(draft.video_prompt)
    header = (
        f"SCENE {window.index:0{number_width}d}  |  "
        f"{format_clock(window.start)} – {format_clock(window.end)}"
    )
    return "\n".join((
        header,
        f"Cần làm gì: {draft.visual}",
        f"Kịch bản:   {speech}",
        "",
        "KEYFRAME:",
        draft.keyframe.strip() or "(missing)",
        "",
        "GROK VIDEO PROMPT:",
        video_prompt,
        "",
        (
            f"Tham số: Image-to-Video, duration {window.duration}, aspect_ratio {aspect}, "
            "resolution 720p, generate_audio true"
        ),
    ))


def _with_constraint(video_prompt: str) -> str:
    text = video_prompt.strip() or "(missing)"
    if text == "(missing)" or "no morphing" in text.lower():
        return text
    if text.endswith("."):
        return f"{text} {_CONSTRAINT}"
    return f"{text}. {_CONSTRAINT}"


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
