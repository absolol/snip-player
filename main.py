"""Точка входа: python main.py [файл]"""

import ctypes
import subprocess
import sys
import traceback
from datetime import datetime

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from player import prefs
from player.child_processes import close_with_player, start_outside
from player.i18n import tr
from player.paths import APP_DIR, APP_NAME, DATA_DIR
from player.single_instance import hand_over_or_listen

ERROR_LOG = DATA_DIR / "error.log"


def _report_error(exc_type, exc, tb):
    """Плеер запускается через pythonw — без консоли ошибки иначе не видно.
    Пишем её в error.log и показываем сообщение."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as log:
            log.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n{text}")
    except OSError:
        pass
    if QApplication.instance():
        try:
            from player import dialogs

            dialogs.error(None, tr("Произошла ошибка"), str(exc), note=tr("Подробности записаны в файл:") + f"\n{ERROR_LOG}")
        except Exception:  # окно в стиле плеера не получилось — хотя бы системное
            QMessageBox.critical(None, APP_NAME, tr("Произошла ошибка. Подробности записаны в файл:") + f"\n{ERROR_LOG}\n\n{exc}")


def main():
    sys.excepthook = _report_error
    close_with_player()  # ffmpeg / ffprobe не переживут плеер

    # Своя «личность» для панели задач: иначе Windows группирует окно с python.exe
    # и показывает иконку Python вместо иконки плеера.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Proigryvatel.Player")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # Плеер уже открыт — отдаём файл ему (он сам поднимет окно) и выходим.
    # Настройка «Открывать новые видео в том же окне» выключена — каждый запуск сам по себе.
    # --start-ms=N — перезапуск после смены языка (MainWindow.restart): продолжить видео с того же места.
    args = [a for a in sys.argv[1:] if not a.startswith("--start-ms=")]
    start = [a for a in sys.argv[1:] if a.startswith("--start-ms=")]
    path = args[0] if args else None
    start_ms = int(start[0].split("=", 1)[1]) if start and start[0].split("=", 1)[1].isdigit() else 0
    server = None
    if prefs.read(QSettings(str(prefs.SETTINGS_PATH), QSettings.Format.IniFormat), "single_instance"):
        server = hand_over_or_listen(path)
        if server is None:
            sys.exit(0)

    try:
        from player.main_window import MainWindow  # после проверки: второй запуск так быстрее

        window = MainWindow()
    except Exception:
        _report_error(*sys.exc_info())
        sys.exit(1)
    if server is not None:
        server.open_requested.connect(window.open_from_other_instance)
        server.show_requested.connect(window.open_from_other_instance)
    window.show()
    if path:
        window.open_file(path, start_ms)

    code = app.exec()
    restart = getattr(window, "restart_command", None)
    if restart:
        if server is not None:
            server.close()  # канал «одного окна» свободен — новый запуск не отдаст файл сюда
        start_outside(restart, cwd=str(APP_DIR), close_fds=True,
                      creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    sys.exit(code)


if __name__ == "__main__":
    main()
