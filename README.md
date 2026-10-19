# Video Joiner

A small PyQt6 desktop app to join multiple video files into one, with
drag-and-drop reordering.

## Setup

```bash
pip install -r requirements.txt
```

Requires FFmpeg. Either have `ffmpeg` on your PATH, or the
`imageio-ffmpeg` package (in requirements.txt) will provide a bundled copy
automatically.

## Run (from source)

```bash
python main.py
```

## Build a standalone .exe

No Python needed to run the result — FFmpeg is bundled in too, via
`imageio-ffmpeg`.

```bash
build_exe.bat
```

or manually:

```bash
pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm VideoJoiner.spec
```

The app appears at `dist\VideoJoiner.exe` — copy that one file anywhere
and double-click it. `videojoiner.log` (errors) is written next to
whichever `.exe`/`main.py` you actually ran.

## Usage — Join Videos tab

1. Drag video files into the window (or click "Add Files...").
   Newly added clips are automatically sorted by file creation time
   (oldest first) — use "Sort by Date" to re-apply that after manually
   reordering, or drag rows / use Move Up / Move Down for a custom order.
2. Choose an output file.
3. Click "Join Videos".

The app first tries a fast, no-re-encode join. If your clips use different
codecs/resolutions, it automatically falls back to normalizing each clip
(re-encoding to a consistent H.264/AAC stream, adding silent audio where a
clip has none) before joining — slower, but works across mismatched
sources.

## Usage — Subtitles tab

Two ways to get subtitle text for a video:

- **Auto-transcribe**: pick a video, choose a Whisper model size (bigger =
  more accurate but slower), and click "Transcribe from Audio". Speech is
  recognized locally (no cloud service) and translated to English by
  default (uncheck "Translate to English" to keep the original spoken
  language instead). The first transcription with a given model size
  downloads it from Hugging Face (needs internet once; cached afterward).
- **Load an existing file**: click "Load Subtitle File..." to bring in a
  `.srt` or a styled `.ass` file (karaoke effects, per-character colors,
  custom fonts — all preserved when burning, via ffmpeg's libass-based
  `subtitles` filter).

Either way, review/edit the text in the preview box, then "Burn Subtitles
onto Video" to hardcode it into a new output file. A custom font used in
an `.ass` file only renders correctly if that font is installed on this
PC — ffmpeg/libass silently falls back to a default font otherwise.

## Usage — YouTube Lyrics tab

1. Paste a YouTube link (watch, youtu.be, Shorts, or embed).
2. Click "Get Transcript". The app reads the video's caption track —
   a manually uploaded track when one exists, otherwise the
   auto-generated captions. It does not download the video.
3. Switch language if the video has more than one caption track.
4. Click "Copy" to put the full text on the clipboard. Check
   "Include timestamps" if you want each line marked with its time.

A video with captions turned off, or an age-restricted video, cannot
be read this way.

## Usage — Scene Prompts tab

1. Paste a public YouTube link and a Gemini API key. The key is saved
   on this PC the next time you scan. Pick a model if the default one
   is not on your key.
2. Click "Scan Scenes". The app reads the video length, cuts the
   caption track into 15-second windows, then asks Gemini to watch
   each window. The video file is not downloaded.
3. A video longer than 5 minutes keeps only the first 20 scenes. The
   app asks before those 20 scenes start, because every scene is its
   own Gemini call. "Cancel" stops after the scene that is already in
   flight and keeps whatever was written.
4. Copy the prompt. Each scene has the picture, the spoken line, a
   keyframe prompt, and a Grok video prompt. Render each scene as its
   own Image-to-Video clip, then join the clips in order.

The last few seconds are left out when they are shorter than 15. A
video with no captions is still scanned; those scenes are marked as
having no speech. Private and unlisted videos cannot be watched this
way.

## Usage — Add Music tab

1. Choose a video and a music file (mp3, wav, m4a, and the other common
   audio types).
2. Choose an output file. It must be a different file from the source video.
3. Click "Add Music".

The picture is copied when the codec fits in an MP4. The video's original
sound is replaced by the music file. If the music is shorter than the
video, it is repeated back-to-back until the output is the same length as
the video. If the music is longer, it is trimmed to the video.

## Notes

- All FFmpeg work runs on a background thread, so the window stays
  responsive during a join.
- Errors are logged to `videojoiner.log` next to `main.py` and also shown
  in a dialog.
