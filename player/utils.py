"""Мелкие вспомогательные функции."""

from .i18n import tr

VIDEO_EXTENSIONS = (
    "mp4 mkv avi mov wmv flv webm m4v mpg mpeg ts m2ts mts 3gp ogv vob divx asf rm rmvb"
).split()


def format_time(ms: int) -> str:
    """12345 → '0:12', 3725000 → '1:02:05'."""
    total = max(int(ms), 0) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def file_dialog_filter() -> str:
    videos = " ".join(f"*.{ext}" for ext in VIDEO_EXTENSIONS)
    return tr("Видео ({videos});;Все файлы (*)", videos=videos)
