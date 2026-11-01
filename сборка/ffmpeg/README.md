# сборка/ffmpeg/

Only needed to build the portable package (`сборка/build.py`). Put **`ffmpeg.exe`** and **`ffprobe.exe`** here —
the release uses the gyan.dev *essentials* build (FFmpeg 9.0.2):
<https://www.gyan.dev/ffmpeg/builds/> → `ffmpeg-release-essentials.7z`, folder `bin`.

If this folder is empty, `build.py` takes FFmpeg from `PATH` (or `--ffmpeg FOLDER`).
When running from source, FFmpeg just needs to be in `PATH`.
