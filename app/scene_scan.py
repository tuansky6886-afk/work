"""Watch a public YouTube video in 15-second slices and write one prompt.

The video file is never downloaded. Length comes from YouTube's player
endpoint. Each slice is sent to the Gemini API as a YouTube URL plus a
clip range, because one request for a long video summarizes and drops shots.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from typing import Any

import requests

from app.scene_utils import (
    SCENE_SECONDS,
    ScanOutput,
    SceneDraft,
    SceneScanError,
    SceneWindow,
    bible_sample_fps,
    parse_scene_response,
    format_clock,
    plan_scenes,
    render_document,
    resolve_aspect,
    speech_for_window,
)
from app.youtube_utils import TranscriptError, extract_video_id, fetch_youtube_transcript

MODEL_CHOICES = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash")
DEFAULT_MODEL = MODEL_CHOICES[0]
# Three tries on one model, then the next model. Waits sit between those tries.
_BUSY_LIMIT = 3
_BUSY_WAITS = (3, 8)
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_LENGTH_RE = re.compile(r'"lengthSeconds":"(\d+)"')
# The web player often answers UNPLAYABLE without a logged-in session.
# This iOS client returns lengthSeconds for a public video.
_IOS_CLIENT = {
    "clientName": "IOS",
    "clientVersion": "20.10.4",
    "deviceMake": "Apple",
    "deviceModel": "iPhone16,2",
    "osName": "iPhone",
    "osVersion": "18.1.0.22B83",
    "hl": "en",
    "gl": "US",
}
_IOS_UA = "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_1_0 like Mac OS X)"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_BIBLE_IN_SCENE = 3000

Progress = Callable[[int, int, str], None]
Confirm = Callable[[int, int, int, bool], bool]


class ScanCancelled(Exception):
    """The user stopped the scan. `output` is set once anything was written."""

    def __init__(self, output: ScanOutput | None = None) -> None:
        super().__init__("Scan cancelled.")
        self.output = output


class VideoFacts:
    def __init__(self, video_id: str, title: str, duration_seconds: int, width: int | None, height: int | None) -> None:
        self.video_id = video_id
        self.title = title
        self.duration_seconds = duration_seconds
        self.width = width
        self.height = height


def scan_to_prompt(
    url: str,
    api_key: str,
    model: str,
    *,
    aspect_override: str | None,
    fast_cuts: bool,
    on_progress: Progress,
    cancel_event: threading.Event,
    confirm_many: Confirm | None = None,
) -> ScanOutput:
    """Scan up to 20 full 15-second scenes and return one document."""
    key = api_key.strip()
    if not key:
        raise SceneScanError("Enter a Gemini API key first.")
    model_name = _clean_model(model)
    try:
        video_id = extract_video_id(url)
    except TranscriptError as exc:
        raise SceneScanError(str(exc)) from exc

    on_progress(0, 0, "Reading the video length...")
    _check(cancel_event)
    facts = fetch_video_facts(video_id)
    plan = plan_scenes(facts.duration_seconds)
    windows = plan.windows
    remainder = plan.remainder
    if plan.capped and confirm_many is not None:
        if not confirm_many(len(windows), facts.duration_seconds, remainder, True):
            raise ScanCancelled()

    on_progress(0, 0, "Reading captions...")
    _check(cancel_event)
    snippets, caption_note = _load_captions(video_id)
    aspect, aspect_source = resolve_aspect(facts.width, facts.height, aspect_override)
    scene_fps = 5 if fast_cuts else 1
    # A capped video locks its look on the same opening that the scenes cover.
    bible_start = 0 if plan.capped else None
    bible_end = windows[-1].end if plan.capped else None
    bible_span = windows[-1].end if plan.capped else facts.duration_seconds

    bible = ""
    drafts: list[SceneDraft] = []
    total = 1 + len(windows)
    # models[0] changes when the chosen model is overloaded, and later scenes stay on that model.
    models = [model_name]
    progress_state = {"done": 0, "total": total}

    def _status(message: str) -> None:
        on_progress(progress_state["done"], progress_state["total"], message)

    try:
        on_progress(0, total, "Locking the look of the people and the place...")
        bible = _watch(
            key,
            models,
            _watch_url(video_id),
            _bible_prompt(),
            start=bible_start,
            end=bible_end,
            fps=bible_sample_fps(bible_span),
            detail=False,
            timeout=300,
            cancel_event=cancel_event,
            on_status=_status,
        )
        for window in windows:
            _check(cancel_event)
            # The look-lock call is step 1, so scene 1 starts with the bar at 1.
            progress_state["done"] = window.index
            on_progress(
                window.index,
                total,
                f"Watching scene {window.index} of {len(windows)} "
                f"({format_clock(window.start)} – {format_clock(window.end)})...",
            )
            speech = speech_for_window(snippets, window.start, window.end)
            visual, keyframe, video_prompt = parse_scene_response(_watch(
                key,
                models,
                _watch_url(video_id),
                _scene_prompt(window, speech, bible),
                start=window.start,
                end=window.end,
                fps=scene_fps,
                detail=True,
                timeout=180,
                cancel_event=cancel_event,
                on_status=_status,
            ))
            drafts.append(SceneDraft(window, visual, speech, keyframe, video_prompt))
        on_progress(total, total, "Writing the prompt...")
    except ScanCancelled:
        if not bible and not drafts:
            raise
        raise ScanCancelled(_make_output(
            facts, aspect, aspect_source, bible, drafts, len(windows), remainder, caption_note,
            stopped=True, capped=plan.capped,
        )) from None

    return _make_output(
        facts, aspect, aspect_source, bible, drafts, len(windows), remainder, caption_note,
        stopped=False, capped=plan.capped,
    )


def fetch_video_facts(video_id: str) -> VideoFacts:
    """Title, length, and frame size for a public video."""
    facts = _facts_from_player(video_id)
    if facts is not None:
        return facts
    facts = _facts_from_watch_page(video_id)
    if facts is not None:
        return facts
    raise SceneScanError("Couldn't read how long this video is. It may be private, deleted, or blocked.")


def _facts_from_player(video_id: str) -> VideoFacts | None:
    try:
        response = requests.post(
            "https://www.youtube.com/youtubei/v1/player",
            params={"prettyPrint": "false"},
            json={"videoId": video_id, "context": {"client": _IOS_CLIENT}},
            headers={"User-Agent": _IOS_UA, "Content-Type": "application/json"},
            timeout=20,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        logging.exception("YouTube player lookup failed")
        return None

    details = data.get("videoDetails") or {}
    length = _positive_int(details.get("lengthSeconds"))
    if length is None:
        return None
    title = details.get("title") if isinstance(details.get("title"), str) else ""
    width, height = _largest_frame(data.get("streamingData") or {})
    return VideoFacts(video_id, title.strip(), length, width, height)


def _facts_from_watch_page(video_id: str) -> VideoFacts | None:
    try:
        response = requests.get(
            _watch_url(video_id),
            headers={"User-Agent": _BROWSER_UA, "Accept-Language": "en-US"},
            timeout=20,
        )
    except requests.RequestException:
        logging.exception("YouTube watch-page lookup failed")
        return None
    if not response.ok:
        return None
    match = _LENGTH_RE.search(response.text)
    if match is None:
        return None
    title = _title_from_oembed(video_id)
    return VideoFacts(video_id, title, int(match.group(1)), None, None)


def _title_from_oembed(video_id: str) -> str:
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": _watch_url(video_id), "format": "json"},
            timeout=15,
        )
        if response.ok:
            title = response.json().get("title")
            if isinstance(title, str):
                return title.strip()
    except (requests.RequestException, ValueError):
        return ""
    return ""


def _load_captions(video_id: str) -> tuple[tuple[tuple[float, str], ...], str]:
    """Captions fill the spoken line. A missing track does not stop the visual scan."""
    try:
        result = fetch_youtube_transcript(video_id)
    except TranscriptError as exc:
        logging.info("Scene scan continued without captions: %s", exc)
        return (), f"Captions: unavailable ({exc}). Spoken lines are marked as no speech."
    return result.snippets, f"Captions: {result.track.label}"


def _watch(
    api_key: str,
    models: list[str],
    video_url: str,
    prompt: str,
    *,
    start: int | None,
    end: int | None,
    fps: float | None,
    detail: bool,
    timeout: int,
    cancel_event: threading.Event,
    on_status: Callable[[str], None] | None = None,
) -> str:
    use_fps = fps
    use_config = True
    use_thinking = True
    use_mime = True
    use_static = True
    use_detail = detail
    last_message = "Gemini did not answer."
    saw_busy = False
    chain = _model_chain(models[0])
    start_index = chain.index(models[0])

    for index in range(start_index, len(chain)):
        current = chain[index]
        if current != models[0]:
            previous = models[0]
            models[0] = current
            if on_status is not None:
                on_status(f"{previous} is busy. Switching to {current}...")
        busy_tries = 0

        def pause_for_demand(message: str, *, model: str = current) -> bool:
            nonlocal busy_tries, saw_busy, last_message
            saw_busy = True
            last_message = message
            if busy_tries >= _BUSY_LIMIT - 1:
                return False
            wait = _BUSY_WAITS[busy_tries]
            busy_tries += 1
            if on_status is not None:
                on_status(f"{model} is busy. Trying again in {wait}s...")
            if cancel_event.wait(wait):
                raise ScanCancelled()
            return True

        while True:
            _check(cancel_event)
            try:
                response = requests.post(
                    _GEMINI_URL.format(model=current),
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=_gemini_body(
                        video_url,
                        prompt,
                        start,
                        end,
                        use_fps,
                        use_config,
                        use_thinking,
                        use_mime,
                        use_static,
                        use_detail,
                    ),
                    timeout=timeout,
                )
            except requests.Timeout as exc:
                raise SceneScanError("Gemini took too long on this scene. Try again.") from exc
            except requests.RequestException as exc:
                raise SceneScanError("Couldn't reach Gemini. Check the connection and try again.") from exc

            message = _error_message(response, api_key)
            if response.status_code in {401, 403}:
                raise SceneScanError(f"Gemini rejected the API key.\n\n{message}")
            if response.status_code == 400:
                dropped = _drop_rejected_field(
                    message,
                    use_fps=use_fps,
                    use_thinking=use_thinking,
                    use_detail=use_detail,
                    use_static=use_static,
                    use_mime=use_mime,
                    use_config=use_config,
                )
                if dropped is not None:
                    use_fps, use_thinking, use_detail, use_static, use_mime, use_config = dropped
                    continue
            if response.status_code == 404:
                last_message = f"The model “{current}” was not found. Change the model name and try again."
                break
            if _is_busy(response.status_code, message):
                if pause_for_demand(message):
                    continue
                break
            if not response.ok:
                raise SceneScanError(message or f"Gemini returned HTTP {response.status_code}.")
            try:
                data = response.json()
            except ValueError as exc:
                raise SceneScanError("Gemini returned something that was not a description.") from exc
            try:
                return _response_text(data)
            except SceneScanError as exc:
                text = str(exc)
                # A thinking trace can fill the output budget and leave no scene text.
                if use_thinking and "MAX_TOKENS" in text:
                    use_thinking = False
                    continue
                if _is_busy(response.status_code, text):
                    if pause_for_demand(text):
                        continue
                    break
                raise

    if saw_busy:
        raise SceneScanError(
            "Gemini is busy on every available model. Wait a minute and scan again.\n\n" + last_message
        )
    raise SceneScanError(last_message)


def _drop_rejected_field(
    message: str,
    *,
    use_fps: float | None,
    use_thinking: bool,
    use_detail: bool,
    use_static: bool,
    use_mime: bool,
    use_config: bool,
) -> tuple[float | None, bool, bool, bool, bool, bool] | None:
    """Turn off the one request field Gemini rejected, or return None."""
    folded = message.lower().replace("_", "").replace(" ", "")
    if use_fps is not None and "fps" in folded:
        return None, use_thinking, use_detail, use_static, use_mime, use_config
    if use_thinking and "thinking" in folded:
        return use_fps, False, use_detail, use_static, use_mime, use_config
    if use_detail and "mediaresolution" in folded:
        return use_fps, use_thinking, False, use_static, use_mime, use_config
    if use_static and "mediaprocessing" in folded:
        return use_fps, use_thinking, use_detail, False, use_mime, use_config
    if use_mime and "mime" in folded:
        return use_fps, use_thinking, use_detail, use_static, False, use_config
    if use_config and "generationconfig" in folded:
        return use_fps, use_thinking, use_detail, use_static, use_mime, False
    return None


def _gemini_body(
    video_url: str,
    prompt: str,
    start: int | None,
    end: int | None,
    fps: float | None,
    use_config: bool,
    use_thinking: bool,
    use_mime: bool,
    use_static: bool,
    use_detail: bool,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if start is not None and end is not None:
        metadata["startOffset"] = f"{start}s"
        metadata["endOffset"] = f"{end}s"
    if fps is not None:
        metadata["fps"] = fps
    file_data: dict[str, Any] = {"fileUri": video_url}
    if use_mime:
        file_data["mimeType"] = "video/*"
    video_part: dict[str, Any] = {"fileData": file_data}
    if metadata:
        video_part["videoMetadata"] = metadata
    # A clip range is ignored unless this part stays in static mode.
    if use_static:
        video_part["mediaProcessing"] = "STATIC"
    if use_detail:
        video_part["mediaResolution"] = "MEDIA_RESOLUTION_HIGH"
    body: dict[str, Any] = {"contents": [{"role": "user", "parts": [video_part, {"text": prompt}]}]}
    if use_config:
        config: dict[str, Any] = {"temperature": 0.2, "maxOutputTokens": 4096}
        if use_thinking:
            config["thinkingConfig"] = {"thinkingLevel": "LOW"}
        body["generationConfig"] = config
    return body


def _response_text(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict) and error.get("message"):
        raise SceneScanError(str(error["message"])[:500])
    feedback = data.get("promptFeedback") or {}
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        raise SceneScanError(f"Gemini blocked this clip ({feedback['blockReason']}).")
    candidates = data.get("candidates") or []
    if not candidates:
        raise SceneScanError("Gemini returned no description.")
    candidate = candidates[0]
    parts = ((candidate.get("content") or {}).get("parts")) or []
    texts = [
        part["text"].strip()
        for part in parts
        if isinstance(part, dict) and not part.get("thought") and isinstance(part.get("text"), str) and part["text"].strip()
    ]
    if texts:
        return "\n".join(texts)
    reason = candidate.get("finishReason")
    if reason and reason != "STOP":
        raise SceneScanError(f"Gemini stopped without a description ({reason}).")
    raise SceneScanError("Gemini returned no description.")


def _bible_prompt() -> str:
    return (
        "Watch this public video and lock the look of the people and the places "
        "so later shots can match. Describe only what you can actually see.\n\n"
        "Return only these sections, in English, with no preamble:\n"
        "CHARACTERS: For each recurring person, approximate age, hair, face, build, "
        "and the exact clothes and accessories. Skip one-off bystanders.\n"
        "WORLD: The recurring locations, time of day, and lighting, in one short paragraph.\n"
        "STYLE: One line on the visual style (live action, animation, or otherwise)."
    )


def _scene_prompt(window: SceneWindow, speech: str, bible: str) -> str:
    spoken = speech.strip() or "[no speech]"
    locked = bible.strip()
    if len(locked) > _BIBLE_IN_SCENE:
        locked = locked[:_BIBLE_IN_SCENE].rstrip() + "…"
    return (
        f"Watch only this clip, from {window.start}s to {window.end}s of the source video. "
        "Describe only what is visible. Do not invent shots.\n\n"
        "The spoken words in this window are fixed. Quote them in the VIDEO audio line "
        "and do not rewrite them:\n"
        f'"""\n{spoken}\n"""\n\n'
        "Locked look, keep it consistent:\n"
        f"{locked or '(none yet)'}\n\n"
        "Return exactly three sections and nothing else. Keep these English labels:\n"
        "VISUAL: 1 to 3 sentences in Vietnamese. Who is on screen, what they do from the "
        "start of this window to the end, and where they are. If the clip cuts, list the cuts in order.\n"
        "KEYFRAME: an English still-image prompt of the first moment, before the motion starts. "
        "Include the locked face, clothes, and place.\n"
        "VIDEO: an English image-to-video prompt in this order: subject, one motion verb, "
        "one camera move, atmosphere, audio (ambience, foley, and the spoken line above in quotes "
        "with the voice tone), then exactly: "
        "natural physics, consistent facial features and outfit, no morphing, no extra fingers, "
        "no text overlay, no watermark."
    )


def _make_output(
    facts: VideoFacts,
    aspect: str,
    aspect_source: str,
    bible: str,
    drafts: list[SceneDraft],
    planned_count: int,
    remainder: int,
    caption_note: str,
    *,
    stopped: bool,
    capped: bool,
) -> ScanOutput:
    text = render_document(
        title=facts.title,
        video_id=facts.video_id,
        duration_seconds=facts.duration_seconds,
        width=facts.width,
        height=facts.height,
        aspect=aspect,
        aspect_source=aspect_source,
        bible=bible,
        drafts=drafts,
        planned_count=planned_count,
        remainder=remainder,
        caption_note=caption_note,
        stopped=stopped,
        capped=capped,
    )
    return ScanOutput(
        text=text,
        title=facts.title or facts.video_id,
        stopped=stopped,
        finished_scenes=len(drafts),
        planned_scenes=planned_count,
    )


def _largest_frame(streaming: dict[str, Any]) -> tuple[int | None, int | None]:
    formats = list(streaming.get("formats") or []) + list(streaming.get("adaptiveFormats") or [])
    best: tuple[int, int] | None = None
    for item in formats:
        width = _positive_int(item.get("width")) if isinstance(item, dict) else None
        height = _positive_int(item.get("height")) if isinstance(item, dict) else None
        if width and height and (best is None or width > best[0]):
            best = (width, height)
    if best is None:
        return None, None
    return best


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _model_chain(selected: str) -> tuple[str, ...]:
    """Selected model first, then the other built-in models."""
    names = [selected]
    for name in MODEL_CHOICES:
        if name not in names:
            names.append(name)
    return tuple(names)


def _is_busy(status: int, message: str) -> bool:
    if status in {429, 500, 502, 503, 504}:
        return True
    folded = message.lower()
    return "high demand" in folded or "overloaded" in folded or "resource exhausted" in folded


def _clean_model(model: str) -> str:
    name = model.strip()
    if name.startswith("models/"):
        name = name[len("models/"):]
    if not name:
        return DEFAULT_MODEL
    if not _MODEL_RE.fullmatch(name):
        raise SceneScanError("The model name has characters Gemini will not accept.")
    return name


def _watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _check(cancel_event: threading.Event) -> None:
    if cancel_event.is_set():
        raise ScanCancelled()


def _error_message(response: requests.Response, api_key: str) -> str:
    try:
        data = response.json()
    except ValueError:
        text = response.text[:400]
    else:
        error = data.get("error") if isinstance(data, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        text = str(message or response.text[:400])
    if api_key and api_key in text:
        text = text.replace(api_key, "[key]")
    text = text.strip()
    if text:
        return text[:500]
    return f"Gemini returned HTTP {response.status_code}."


# Re-exported so callers can share the scene length without importing two names.
__all__ = [
    "DEFAULT_MODEL",
    "MODEL_CHOICES",
    "SCENE_SECONDS",
    "ScanCancelled",
    "fetch_video_facts",
    "scan_to_prompt",
]
