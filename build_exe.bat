@echo off
REM Rebuilds dist\VideoJoiner.exe — a standalone, double-click-able app
REM with FFmpeg bundled inside (via imageio-ffmpeg), so it also works on a
REM machine with no FFmpeg installed.
pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm VideoJoiner.spec
echo.
echo Done. The app is at dist\VideoJoiner.exe
pause
