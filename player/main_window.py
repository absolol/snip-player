"""Главное окно: собирает видео, панель управления, меню и горячие клавиши."""

import hashlib
import os
import re
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QFile, QPoint, QRect, QSettings, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QImage, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import anim_button
from . import dialogs, registration
from .app_icon import make_app_icon
from .child_processes import start_outside
from .prefs import SETTINGS_PATH, Prefs
from .hotkeys_window import HotkeysWindow
from .settings_window import SettingsWindow
from .clipboard import copy_image
from .controls import ControlBar, SlideHolder
from .edit_bar import EditBar
from .editor import CutList
from .floating_panel import FloatingPanel
from .engine import MpvEngine
from .exporter import CANCELLED, Exporter
from .i18n import rate as rate_text
from .i18n import tr, tr_in
from .info_panel import InfoPanel
from .media_info import MediaInfoLoader
from .overlay import VideoOverlay
from .paths import APP_DIR, APP_NAME, FROZEN
from .single_instance import bring_to_front
from .smooth_popups import SmoothPopups
from .space_key import SpaceKey
from .themes import (CUSTOM_THEME, DEFAULT_THEME, build_custom_theme, build_stylesheet, icon_font, load_themes,
                     notify_shade)
from .title_bar import TitleBar, TitleCapsule
from .utils import VIDEO_EXTENSIONS, file_dialog_filter, format_time
from .video_mouse import VideoMouseTracker
from .waveform import WaveformLoader
from .window_chrome import WindowChrome

# Шаги перемотки и громкости, ускорение при удержании, уведомления, скриншоты — в настройках (prefs.py).
CONTROLS_HIDE_DELAY_MS = 2000
SETTINGS_LOOK_PAGE = 1  # раздел «Внешний вид» в окне настроек (шестерёнка → «Оформление…»)
SCREENSHOT_SUBFOLDER = APP_NAME  # папка внутри «Изображений», если в настройках не выбрана другая

# Ускорение при удержании левой кнопки мыши над видео (стартовая скорость и предел — в настройках).
HOLD_RATE_MIN = 1.0       # предел при движении мыши влево
HOLD_PIXELS_PER_X = 150   # на сколько пикселей сдвинуть мышь, чтобы скорость изменилась на 1×

# Продолжение просмотра с места остановки: место запоминается, только если оно не в самом начале
# и не у конца (досмотренное видео в следующий раз начинается сначала).
RESUME_MIN_MS = 5000
RESUME_END_MARGIN_MS = 10000
RESUME_MAX_FILES = 300
RESUME_MESSAGE_MS = 60_000  # «Продолжаем с …» — только если продолжили дальше первой минуты


class MainWindow(QMainWindow):
    _screenshotDone = Signal(str, bool)  # из потока mpv — в главный поток

    def __init__(self):
        super().__init__()
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
        self._smooth_popups = SmoothPopups(QApplication.instance())
        self.settings = QSettings(str(SETTINGS_PATH), QSettings.Format.IniFormat)
        self.prefs = Prefs(self.settings, self)
        self.settings_window = None  # создаётся при первом открытии
        self.hotkeys_window = None
        self._was_ended = False
        self.engine = MpvEngine()
        self.themes = load_themes()
        self.themes.pop("neon", None)  # «Неон» заменён «Своей» темой (на случай старой копии файла)
        self.themes[CUSTOM_THEME] = self._custom_theme()
        self._error_shown = False

        # Системный заголовок заменён своим (title_bar.py); поведение окна Windows
        # сохраняется через window_chrome.py.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(560, 360)
        self.setAcceptDrops(True)

        self._base_rate = 1.0   # скорость, выбранная в списке на панели
        self._hold_rate = None  # скорость во время удержания мыши (None — не удерживают)

        # Редактор: удалённые куски, выделение и несохранённые изменения.
        self.cuts = CutList()
        self._selected: set[int] = set()  # выделенные куски (номера)
        self._editing = False
        self._cuts_dirty = False
        self._known_length = 0
        self.exporter = Exporter(self)
        self.exporter.progress.connect(lambda f: self.edit_bar.set_progress(f))
        self.exporter.status.connect(lambda text: self.edit_bar.set_status(text))
        self.exporter.finished.connect(self._on_export_finished)
        # Звуковая волна под шкалой редактора — считается в фоне, только пока открыт редактор.
        self.waveform = WaveformLoader(self)
        self.waveform.ready.connect(self._on_waveform_ready)
        self._wave_key = None  # (путь, дорожка), волна которой показана или считается

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()

        self.speed_overlay = VideoOverlay(self)
        # Короткие сообщения поверх видео («Скриншот сохранён», «Повтор включён»).
        self.message_overlay = VideoOverlay(self, replace_animated=True)
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.message_overlay.hide_animated)
        self._screenshotDone.connect(self._on_screenshot_done)
        self.mouse_tracker = VideoMouseTracker(self.video_frame, self)
        self.mouse_tracker.holdStarted.connect(lambda: self._update_speed_hold(0))
        self.mouse_tracker.holdMoved.connect(self._update_speed_hold)
        self.mouse_tracker.holdEnded.connect(self._end_speed_hold)
        self.mouse_tracker.clicked.connect(self.toggle_play)

        # Пробел: нажатие — пауза / воспроизведение, удержание — 2×.
        self.space_key = SpaceKey(self)
        self.space_key.tapped.connect(self.toggle_play)
        self.space_key.holdStarted.connect(self._on_space_hold)
        self.space_key.holdEnded.connect(self._end_speed_hold)
        self.mouse_tracker.doubleClicked.connect(self.toggle_fullscreen)

        self.chrome = WindowChrome(self, self.title_bar)
        self.chrome.install()
        self.engine.attach(int(self.video_frame.winId()))
        self.engine.set_volume(int(self.settings.value("volume", 80)))
        self.controls.set_volume(self.engine.volume)
        self._update_volume_icon()
        # Оформление — всегда «своё» (выбора темы нет): основа + цвета из настроек. Старые темы переносятся:
        # «Тёмная» / «Светлая» → та же основа, «Неон» → тёмная основа с розовым.
        old_theme = str(self.settings.value("theme", CUSTOM_THEME))
        if old_theme == "neon":
            self.prefs.set("custom_base", "dark")
            self.prefs.set("custom_accent", "#ff3ea5")
            self.prefs.set("custom_notify", "same")
        elif old_theme in ("dark", "light"):
            self.prefs.set("custom_base", old_theme)
        self.themes[CUSTOM_THEME] = self._custom_theme()
        self.apply_theme(CUSTOM_THEME)
        for key in ("window_outline", "show_stop", "seek_step", "end_action", "export_quality", "save_mode"):
            self._apply_pref(key)
        self.prefs.changed.connect(self._apply_pref)

        # Размер и положение окна — в самом конце, когда заголовок и обработка окна уже готовы:
        # восстановление развёрнутого окна сразу вызывает события, которым они нужны.
        if not self.restoreGeometry(self.settings.value("geometry", b"")):
            self.resize(1100, 680)

        self.timer = QTimer(self)
        self.timer.setInterval(50)  # часто, чтобы при просмотре точнее перепрыгивать вырезанные куски
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # --- Построение интерфейса --------------------------------------------

    def _build_ui(self):
        self.video_frame = QFrame()
        self.video_frame.setObjectName("video")
        # mpv рисует в собственное окно Windows внутри этого виджета. Только он должен быть
        # таким «настоящим» окном: если Qt сделает настоящими и соседей/родителей (заголовок,
        # панель), Windows будет спрашивать про перетаскивание и края их, а не главное окно.
        self.video_frame.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)

        self.placeholder = self._build_placeholder()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(self.video_frame)

        self.edit_bar = EditBar()
        self.edit_bar.splitClicked.connect(self.split_here)
        self.edit_bar.deleteClicked.connect(self.toggle_delete)
        self.edit_bar.undoClicked.connect(self.undo_cut)
        self.edit_bar.redoClicked.connect(self.redo_cut)
        self.edit_bar.resetClicked.connect(self.reset_cuts)
        self.edit_bar.saveRequested.connect(self.save_cut_video)
        self.edit_bar.save_button.modeChanged.connect(lambda _mode: self._refresh_editor())
        self.edit_bar.cancelExportClicked.connect(lambda: self.exporter.cancel())
        tracks = self.edit_bar.tracks_button
        tracks.listenRequested.connect(self.engine.set_audio_track)
        tracks.listenRequested.connect(self._update_waveform)  # волна — той дорожки, которую слышно
        tracks.current_track = self.engine.audio_track

        self.controls = ControlBar(self.edit_bar)
        self.controls.editClicked.connect(self.toggle_editor)
        self.controls.timeline.segmentClicked.connect(self._on_segment_clicked)
        self.controls.timeline.markerMoved.connect(self._on_marker_moved)
        self.controls.timeline.markerRemoveRequested.connect(self._on_marker_remove)
        self.controls.playClicked.connect(self.toggle_play)
        self.controls.stopClicked.connect(self.stop)
        self.controls.seekRequested.connect(self.engine.seek)
        self.controls.scrubRequested.connect(self.engine.scrub)
        self.controls.volumeChanged.connect(self.set_volume)
        self.controls.muteClicked.connect(self.toggle_mute)
        self.controls.rateChanged.connect(self._set_base_rate)
        self.controls.fullscreenClicked.connect(self.toggle_fullscreen)
        self.controls.seekByClicked.connect(self.engine.seek_by)
        self.controls.fileStepClicked.connect(self.step_file)
        self.controls.frameStepClicked.connect(self.step_frame)
        self.controls.screenshotClicked.connect(self.take_screenshot)
        self.controls.repeatToggled.connect(self._set_repeat)
        self.controls.onTopToggled.connect(self._set_on_top)

        self.title_bar = TitleBar()
        self.title_bar.minimizeClicked.connect(self.showMinimized)
        self.title_bar.maximizeClicked.connect(self.toggle_maximized)
        self.title_bar.closeClicked.connect(self.close)
        self.title_bar.titleClicked.connect(lambda: self._toggle_info(self.title_bar.title_label))
        self.title_bar.pinClicked.connect(lambda: self.controls.on_top_action.setChecked(False))
        self.title_bar.set_title(APP_NAME)
        self.setMenuWidget(self.title_bar)

        # Сведения о видео: щелчок по капсуле с именем файла.
        self.media_info = MediaInfoLoader(self)
        self.media_info.ready.connect(self._on_media_info_ready)
        self.info_panel = InfoPanel(self)
        self.info_panel.closed.connect(self._on_info_closed)
        self._info_anchor = None

        # Во весь экран имя файла — отдельной капсулой сверху; появляется вместе с панелью, когда двигают мышь.
        self.fs_title_panel = FloatingPanel(self, edge="top")
        self.fs_title = TitleCapsule(self.fs_title_panel)
        self.fs_title.setProperty("floating", True)
        self.fs_title.setFixedHeight(TitleBar.PILL_HEIGHT - 4)
        self.fs_title.clicked.connect(lambda: self._toggle_info(self.fs_title))
        self.fs_title.hide()
        self._fs_title_attached = False

        # Видео над краями окна перехватывает мышь, поэтому в обычном (не развёрнутом)
        # окне у него по бокам тонкие поля — за них можно тянуть, чтобы менять размер.
        self.video_area = QWidget()
        self.video_area.setObjectName("videoArea")
        self.video_area.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        video_layout = QVBoxLayout(self.video_area)
        video_layout.setSpacing(0)
        video_layout.addWidget(self.stack)
        self._update_resize_margins()

        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.controls_holder = SlideHolder(self.controls)
        self.floating_panel = FloatingPanel(self)  # панель поверх видео во весь экран
        layout.addWidget(self.video_area, 1)
        layout.addWidget(self.controls_holder)
        self.setCentralWidget(central)

        # Автоскрытие панели в полноэкранном режиме. Движения мыши над видео
        # получает mpv, а не Qt, поэтому положение курсора опрашивается таймером.
        self._last_cursor_pos = None
        self._cursor_poll = QTimer(self)
        self._cursor_poll.setInterval(100)
        self._cursor_poll.timeout.connect(self._poll_cursor)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(CONTROLS_HIDE_DELAY_MS)
        self._idle_timer.timeout.connect(self._hide_controls_if_idle)

    def _build_placeholder(self) -> QWidget:
        page = QWidget()
        page.setObjectName("placeholder")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        icon = QLabel("")
        icon.setObjectName("placeholderIcon")
        text = QLabel(tr("Перетащите видео сюда или откройте файл"))
        text.setObjectName("placeholderText")
        button = QPushButton(tr("Открыть файл"))
        button.setObjectName("primaryButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(self.open_dialog)

        layout = QVBoxLayout(page)
        layout.addStretch(1)
        for widget in (icon, text, button):
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(14)
        layout.addStretch(1)
        return page

    def _build_menu(self):
        """Быстрое меню шестерёнки — единственное меню (строки «Файл / Вид / Справка» в заголовке нет)."""
        # По просьбе пользователя (30.10.2026) в шестерёнке нет «Открыть файл» (Ctrl+O, перетаскивание)
        # и «Повтор» (клавиша L, настройки); вместо «Темы» — «Оформление»: настройки → «Внешний вид».
        quick = self.controls.quick_menu
        self.theme_actions = {}  # выбора темы в меню больше нет (см. apply_theme)
        quick.addAction(tr("Оформление…"), lambda: self.show_settings(page=SETTINGS_LOOK_PAGE))
        settings_action = QAction(tr("Настройки…") + "\tCtrl+,", self)
        settings_action.triggered.connect(self.show_settings)
        quick.addAction(settings_action)
        quick.addAction(tr("Горячие клавиши"), self._show_hotkeys)

    def _build_shortcuts(self):
        bindings = {
            "Right": lambda: self.engine.seek_by(self.prefs.get("seek_step") * 1000),
            "Left": lambda: self.engine.seek_by(-self.prefs.get("seek_step") * 1000),
            "Shift+Right": lambda: self.engine.seek_by(self.prefs.get("seek_small_step") * 1000),
            "Shift+Left": lambda: self.engine.seek_by(-self.prefs.get("seek_small_step") * 1000),
            "Up": lambda: self.set_volume(self.engine.volume + self.prefs.get("volume_step")),
            "Down": lambda: self.set_volume(self.engine.volume - self.prefs.get("volume_step")),
            "Ctrl+,": self.show_settings,
            "Ctrl+O": self.open_dialog,
            "Ctrl+Q": self.close,
            "M": self.toggle_mute,
            "F": self.toggle_fullscreen,
            "P": self.take_screenshot,
            "L": self.controls.repeat_action.toggle,
            "PgUp": lambda: self.step_file(-1),
            "PgDown": lambda: self.step_file(1),
            "Escape": self._on_escape,
            ".": self.engine.next_frame,
            ",": self.engine.prev_frame,
            "C": self.toggle_editor,
            # Клавиши редактора работают, только когда он открыт.
            "S": lambda: self._if_editing(self.split_here),
            "Ctrl+X": lambda: self._if_editing(self.toggle_delete),
            "Delete": lambda: self._if_editing(self.toggle_delete),
            "Ctrl+Z": lambda: self._if_editing(self.undo_cut),
            "Ctrl+Y": lambda: self._if_editing(self.redo_cut),
            "Ctrl+Shift+Z": lambda: self._if_editing(self.redo_cut),
            "Ctrl+S": lambda: self._if_editing(lambda: self.save_cut_video(self.edit_bar.save_button.mode)),
        }
        for keys, handler in bindings.items():
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(handler)

    # --- Файлы ------------------------------------------------------------

    def open_dialog(self):
        start_dir = str(self.settings.value("last_dir", ""))
        path, _ = QFileDialog.getOpenFileName(self, tr("Открыть видео"), start_dir, file_dialog_filter())
        if path:
            self.open_file(path)

    def open_file(self, path: str, start_ms: int = 0):
        if self.exporter.running:
            dialogs.info(self, tr("Идёт сохранение видео"), tr("Дождитесь окончания — потом можно будет открыть другой файл."))
            return
        if not self._confirm_discard_cuts():
            return
        path = str(Path(path).resolve())
        self._remember_position()
        resumed = 0
        if start_ms <= 0 and self.prefs.get("resume"):
            start_ms = resumed = self._saved_position(path)
        self.settings.setValue("last_dir", str(Path(path).parent))
        self._error_shown = False
        self._was_ended = False
        self.stack.setCurrentWidget(self.video_frame)
        if not self.video_area.property("media"):
            self.video_area.setProperty("media", True)
            self.video_area.style().unpolish(self.video_area)
            self.video_area.style().polish(self.video_area)
        self.engine.open(path, start_ms)
        self.controls.set_media_loaded(True)
        self.setWindowTitle(f"{Path(path).name} — {APP_NAME}")
        self.title_bar.set_title(Path(path).name, clickable=True)
        self.fs_title.set_title(Path(path).name, clickable=True)
        self.info_panel.close()
        self.edit_bar.tracks_button.set_tracks([])  # дорожки нового файла — когда ffprobe их прочитает
        self.media_info.load(path)
        # Кнопки «пред. / след. видео» — только если в папке есть другие видео.
        self.controls.set_has_neighbors(len(self._folder_videos(Path(path))) > 1)
        if self.isFullScreen():
            if self._fs_title_attached:
                self.fs_title_panel.place()  # имя другой длины — капсула другой ширины
            else:
                self.fs_title_panel.attach(self.fs_title, self.screen().geometry())
                self._fs_title_attached = True
        self._wave_key = None
        self.controls.timeline.set_waveform(None)
        self._update_waveform(0)  # у нового файла звучит первая дорожка
        self.cuts.reset()
        self._cuts_dirty = False
        self._selected.clear()
        self._known_length = 0
        self._refresh_editor()
        if resumed >= RESUME_MESSAGE_MS:  # короткий пропуск не объявляем — надпись не мелькает каждый раз
            self.show_message(tr("Продолжаем с {time}", time=format_time(resumed)))

    def open_from_other_instance(self, path: str = ""):
        """Второй запуск плеера (двойной щелчок по видео) передал файл сюда: поднять окно и открыть."""
        bring_to_front(self)
        modal = QApplication.activeModalWidget()
        if modal is not None:  # открыт вопрос или выбор файла — не мешаем ему, просто показываем
            bring_to_front(modal)
            return
        if path:
            self.open_file(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_file(url.toLocalFile())
                break

    # --- Воспроизведение и звук -------------------------------------------

    def toggle_play(self):
        self.engine.toggle()

    def stop(self):
        self.engine.stop()

    def set_volume(self, value: int):
        self.engine.set_volume(value)
        self.controls.set_volume(self.engine.volume)
        if self.engine.muted and value > 0:
            self.toggle_mute()
        self._update_volume_icon()

    def toggle_mute(self):
        self.engine.set_muted(not self.engine.muted)
        self._update_volume_icon()

    def _update_volume_icon(self):
        # Громкость 0 — тоже «без звука»: динамик с крестиком.
        self.controls.set_muted(self.engine.muted or self.engine.volume == 0)

    # --- Кнопки панели: файлы в папке, кадры, скриншот, повтор, поверх окон ---

    @staticmethod
    def _folder_videos(current: Path) -> list[Path]:
        """Видео из папки файла current, по имени («видео 2» раньше «видео 10»)."""
        try:
            files = [f for f in current.parent.iterdir()
                     if f.is_file() and f.suffix.lower().lstrip(".") in VIDEO_EXTENSIONS]
        except OSError:
            return []

        def natural(f: Path):
            return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", f.name.lower())]

        return sorted(files, key=natural)

    def step_file(self, step: int):
        """Открыть предыдущее (step=-1) или следующее (+1) видео из той же папки (по имени)."""
        if not self.engine.has_media:
            return
        current = Path(self.engine.path)
        files = self._folder_videos(current)
        names = [f.name.lower() for f in files]
        index = names.index(current.name.lower()) if current.name.lower() in names else -1
        target = index + step
        if index < 0 or not 0 <= target < len(files):
            self.show_message(tr("Это первое видео в папке") if step < 0 else tr("Это последнее видео в папке"))
            return
        self.open_file(str(files[target]))

    def step_frame(self, step: int):
        if step < 0:
            self.engine.prev_frame()
        else:
            self.engine.next_frame()

    def screenshot_folder(self) -> str:
        """Папка скриншотов: из настроек или «Изображения\\Snip Player»."""
        chosen = self.prefs.get("screenshot_dir")
        if chosen:
            return chosen
        pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        return str(Path(pictures) / SCREENSHOT_SUBFOLDER)

    def take_screenshot(self):
        """P: текущий кадр в полном размере видео — в папку скриншотов (PNG / JPG) и в буфер обмена."""
        if not self.engine.has_media or not self.engine.has_video():
            return
        folder = Path(self.screenshot_folder())
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.show_message(tr("Не удалось создать папку для скриншотов"))
            return
        ms = self.engine.time()
        stamp = format_time(ms).replace(":", "-") + f".{ms % 1000:03d}"
        ext = self.prefs.get("screenshot_format")  # mpv выбирает формат по расширению файла
        path = folder / f"{Path(self.engine.path).stem} — {stamp}.{ext}"
        number = 2
        while path.exists():
            path = folder / f"{Path(self.engine.path).stem} — {stamp} ({number}).{ext}"
            number += 1
        self.engine.screenshot(str(path), lambda ok: self._screenshotDone.emit(str(path), ok))

    def _on_screenshot_done(self, path: str, ok: bool):
        image = QImage(path) if ok else QImage()
        if image.isNull():
            self.show_message(tr("Не удалось сделать скриншот"))
            return
        where = tr("Изображения") if not self.prefs.get("screenshot_dir") else Path(path).parent.name
        if not self.prefs.get("screenshot_clipboard"):
            self.show_message(tr("Скриншот сохранён в «{where}»", where=where))
        elif copy_image(image):
            self.show_message(tr("Скриншот сохранён в «{where}» и скопирован", where=where))
        else:
            self.show_message(tr("Скриншот сохранён в «{where}» (буфер обмена занят)", where=where))

    def _set_repeat(self, repeat: bool):
        """Повтор (L, шестерёнка) — та же настройка, что «В конце видео → Повтор», и запоминается.
        Выключили — возвращается прежнее действие в конце видео (остановиться / следующее в папке)."""
        current = self.prefs.get("end_action")
        if repeat and current != "repeat":
            self._end_action_before_repeat = current
        self.prefs.set("end_action", "repeat" if repeat else getattr(self, "_end_action_before_repeat", "stop"))
        self.show_message(tr("Повтор включён") if repeat else tr("Повтор выключен"))

    def _set_on_top(self, on_top: bool):
        self.chrome.set_topmost(on_top)
        self.title_bar.set_pinned(on_top)  # булавка в заголовке, пока окно поверх всех
        self.show_message(tr("Поверх всех окон") if on_top else tr("Обычное окно"))

    def show_message(self, text: str):
        """Надпись поверх видео (если уведомления не выключены в настройках)."""
        if not self.prefs.get("messages"):
            return
        area = self.video_frame if self.stack.currentWidget() is self.video_frame else self.placeholder
        self.speed_overlay.hide_animated()  # на месте надписи — одно сообщение за раз
        self.message_overlay.show_text(text, self._overlay_area(area))
        self._message_timer.start(round(self.prefs.get("message_seconds") * 1000))

    def _overlay_area(self, area: QWidget) -> QRect:
        """Где показывать надписи поверх видео (глобальные координаты). Во весь экран у верхнего края
        живёт капсула с именем файла — надписи ниже неё, иначе «Повтор включён» ложился на название."""
        rect = QRect(area.mapToGlobal(QPoint(0, 0)), area.size())
        if self.isFullScreen():
            rect.setTop(rect.top() + FloatingPanel.TOP_MARGIN + self.fs_title.height() + 4)
        return rect

    # --- Ускорение удержанием мыши ----------------------------------------

    def _set_base_rate(self, rate: float):
        self._base_rate = rate
        if self._hold_rate is None:
            self.engine.set_rate(rate)

    def _update_speed_hold(self, dx: int):
        if self._hold_rate is None and not self.engine.is_playing():
            return  # на паузе удержание ничего не делает
        rate = self.prefs.get("hold_rate") + dx / HOLD_PIXELS_PER_X
        rate = round(min(max(rate, HOLD_RATE_MIN), self.prefs.get("hold_rate_max")), 2)
        if rate == self._hold_rate:
            return
        self._hold_rate = rate
        self.engine.set_rate(rate)
        # Скорость — на том же месте, что и сообщения («Повтор включён»): прежнее сообщение уходит.
        self._message_timer.stop()
        self.message_overlay.hide_animated()
        # 2.0 → «2,0×», 2.25 → «2,25×» — с запятой, как в настройках (по-английски — с точкой)
        self.speed_overlay.show_text(f"{rate_text(rate)}  ▶▶", self._overlay_area(self.video_frame))

    def _on_space_hold(self):
        if not self.engine.is_playing():
            self.space_key.cancel_hold()  # на паузе удержание пробела — просто нажатие
            return
        self._update_speed_hold(0)  # 2×, как сразу после нажатия кнопки мыши на видео

    def _end_speed_hold(self):
        if self._hold_rate is None:
            return
        self._hold_rate = None
        self.engine.set_rate(self._base_rate)
        self.speed_overlay.hide_animated()

    def _tick(self):
        self.engine.tick()
        self._skip_removed_piece()
        if self._editing and not self._selected:
            self._update_delete_button()  # без выделения кнопка — про кусок под курсором, он меняется
        length = self.engine.length()
        self.controls.timeline.set_playback(self.engine.is_playing(), self.engine.rate)
        self.controls.set_time(self.engine.time(), length)
        if length != self._known_length:  # длительность стала известна после открытия файла
            self._known_length = length
            self._refresh_editor()
        self.controls.set_playing(self.engine.is_playing())
        ended = self.engine.has_media and self.engine.is_ended()
        if ended and not self._was_ended:
            self._on_video_ended()
        self._was_ended = ended
        if self.engine.is_error() and not self._error_shown:
            self._error_shown = True
            dialogs.error(self, tr("Не удалось открыть файл"), Path(self.engine.path).name,
                          note=f"{self.engine.path}\n\n" + tr("Возможно, файл повреждён или это не видео."))

    # --- Редактор ---------------------------------------------------------

    def toggle_editor(self):
        if not self.engine.has_media and not self._editing:
            return
        self._editing = not self._editing
        if not self._editing:
            self._selected.clear()
        holder = self.controls_holder
        # Ряд редактора выезжает из-под видео (или уходит под него): панель плавно растёт / сжимается,
        # видео плавно меняет размер. Высоты без редактора и с ним узнаём заранее; толщина шкалы —
        # прямо из текущей высоты панели (в том же кадре, повторное нажатие посреди анимации — без скачка).
        # Во весь экран панель — отдельное окно поверх видео: на каждом кадре оно меняет высоту и место
        # одним setGeometry (FloatingPanel.place), нижний край у края экрана; видео не меняется.
        timeline = self.controls.timeline
        start = holder.height()
        self.controls.set_editing(False, keep_zoom=True)
        closed = self.controls.sizeHint().height()
        self.controls.set_editing(True, keep_zoom=True)
        opened = self.controls.sizeHint().height()

        def step(height: int):
            timeline.set_edit_progress((height - closed) / max(opened - closed, 1))

        self.controls.set_editing(True, morph=True)
        step(start)
        fullscreen = self.isFullScreen()

        def finished():
            if not self._editing:
                self.controls.set_editing(False)
            if fullscreen and self.isFullScreen():
                holder.child_resized()
                self.floating_panel.place()

        holder.grow_to(opened if self._editing else closed, finished, on_step=step,
                       after_step=self.floating_panel.place if fullscreen else None)
        self._show_controls(True)
        self._refresh_editor()
        self._update_waveform()

    def _update_waveform(self, track: int | None = None):
        """Волна в редакторе — дорожки track (с 0), по умолчанию той, что звучит сейчас."""
        if not (self._editing and self.engine.has_media):
            return
        if track is None:
            track = self.engine.audio_track() or 0
        key = (self.engine.path, track)
        if key == self._wave_key:
            return
        self._wave_key = key
        self.controls.timeline.set_waveform(self.waveform.get(*key))  # None — пока считается, полоса пустая
        self.waveform.load(*key)

    def _on_waveform_ready(self, path: str, track: int):
        if (path, track) == self._wave_key:
            self.controls.timeline.set_waveform(self.waveform.get(path, track))

    def _if_editing(self, action):
        if self._editing and not self.exporter.running:
            action()

    def _on_escape(self):
        if self.info_panel.isVisible():
            self.info_panel.close()
        elif self.isFullScreen():
            self._exit_fullscreen()
        elif self._editing:
            self.toggle_editor()

    def split_here(self):
        """S: разрезать видео в текущей позиции."""
        if self._apply_cut(self.cuts.split(self.engine.time(), self.engine.length())):
            self._selected.clear()  # номера кусков сдвинулись
            self._refresh_editor()

    def _delete_targets(self) -> set[int]:
        """Какие куски удалит / вернёт «Удалить кусок» (Ctrl+X): выделенные или кусок под курсором."""
        return self._selected or {self.cuts.segment_at(self.engine.time())}

    def _update_delete_button(self):
        targets = [i for i in self._delete_targets() if 0 <= i < len(self.cuts.removed_flags)]
        restore = bool(targets) and bool(self.cuts.markers) and all(self.cuts.removed_flags[i] for i in targets)
        self.edit_bar.set_delete_mode(restore, several=len(targets) > 1)

    def toggle_delete(self):
        """Ctrl+X: пометить выделенные куски на удаление или вернуть их.
        Если ничего не выделено — кусок под курсором воспроизведения."""
        if not self.cuts.markers:
            return  # без разрезов кусок один — всё видео: удалять нечего
        self._apply_cut(self.cuts.toggle(self._delete_targets()))

    def _on_segment_clicked(self, index: int, ctrl: bool):
        if ctrl:
            self._selected ^= {index}
        else:
            self._selected = {index}
        self._refresh_editor()

    def _on_marker_moved(self, index: int, ms: int):
        self._apply_cut(self.cuts.move_marker(index, ms, self.engine.length()))
        self._refresh_editor()  # даже если не сдвинулся — вернуть маркер на место на экране

    def _on_marker_remove(self, index: int):
        if self._apply_cut(self.cuts.remove_marker(index)):
            self._selected.clear()
            self._refresh_editor()

    def undo_cut(self):
        if self._apply_cut(self.cuts.undo()):
            self._selected.clear()
            self._refresh_editor()

    def redo_cut(self):
        if self._apply_cut(self.cuts.redo()):
            self._selected.clear()
            self._refresh_editor()

    def reset_cuts(self):
        if self._apply_cut(self.cuts.clear()):
            self._selected.clear()
            self._refresh_editor()

    def _apply_cut(self, changed: bool) -> bool:
        if changed:
            self._cuts_dirty = True
            self._refresh_editor()
        return changed

    def _refresh_editor(self):
        length = self.engine.length()
        busy = self.exporter.running
        self._selected = {i for i in self._selected if i <= len(self.cuts.markers)}
        self.controls.timeline.set_segments(self.cuts.markers, self.cuts.removed_flags)
        self.controls.timeline.set_selection(self._selected)

        kept = self.cuts.kept_duration(length) if length else 0
        pieces = self._pieces_to_save() if length else []
        self.edit_bar.save_button.set_pieces_count(len(pieces))
        if self.edit_bar.save_button.mode == "pieces":  # куски отдельно — нужны разрезы, удалять не обязательно
            can_save = bool(self.cuts.markers) and bool(pieces) and not busy
        else:
            can_save = self.cuts.has_cuts and kept > 0 and not busy
        self.edit_bar.update_state(
            can_split=bool(length) and not busy,
            can_delete=bool(length) and bool(self.cuts.markers) and not busy,  # без разрезов кусок один — всё видео
            can_undo=self.cuts.can_undo and not busy,
            can_redo=self.cuts.can_redo and not busy,
            has_changes=self.cuts.has_changes and not busy,
            can_save=can_save,
            removed_count=self.cuts.removed_count,
        )
        self._update_delete_button()

    def _skip_removed_piece(self):
        """При просмотре перепрыгивает вырезанные куски — так видно, каким будет итог."""
        if not self.cuts.has_cuts or not self.engine.is_playing():
            return
        piece = self.cuts.range_at(self.engine.time(), self.engine.length())
        if piece is None:
            return
        start, end = piece
        if end >= self.engine.length():
            if self.controls.repeat_action.isChecked():
                self.engine.seek(0)  # повтор: с начала (вырезанное начало перепрыгнется следующим тиком)
            else:
                self.engine.pause()  # дальше в итоговом видео ничего нет
        else:
            self.engine.seek(end)

    def _pieces_to_save(self) -> list[tuple[int, int, int]]:
        """«Сохранить куски отдельно»: (номер куска, начало, конец) — выделенные, а если ничего не выделено, все;
        удаляемые куски не сохраняются, даже выделенные."""
        segments = self.cuts.segments(self.engine.length())
        chosen = sorted(self._selected) if self._selected else range(len(segments))
        return [(i, *segments[i][:2]) for i in chosen
                if i < len(segments) and not segments[i][2] and segments[i][1] - segments[i][0] >= 1]

    def _save_pieces(self, src: Path, lossless: bool):
        """Каждый кусок — свой файл «имя — кусок N» в выбранной папке (существующие не перезаписываются)."""
        pieces = self._pieces_to_save()
        if not pieces:
            return
        folder = QFileDialog.getExistingDirectory(self, tr("Папка для кусков"), str(src.parent))
        if not folder:
            return
        outputs, taken = [], set()
        for index, start, end in pieces:
            base = tr("{stem} — кусок {n}", stem=src.stem, n=index + 1)
            dst = Path(folder) / f"{base}{src.suffix}"
            number = 2
            while dst.exists() or dst in taken or dst.resolve() == src.resolve():
                dst = Path(folder) / f"{base} ({number}){src.suffix}"
                number += 1
            taken.add(dst)
            outputs.append((str(dst), [(start, end)]))
        self._pending_replace = None
        self._pending_pieces = True
        self.edit_bar.set_exporting(True)
        self.exporter.start_many(str(src), outputs, lossless, self.prefs.get("encoder"),
                                 self.edit_bar.tracks_button.selection)
        self._refresh_editor()

    def save_cut_video(self, mode: str = "copy"):
        """mode: "copy" — в новый файл; "replace" — заменить исходный файл (старый — в корзину);
        "pieces" — каждый (выделенный) кусок отдельным файлом."""
        length = self.engine.length()
        if mode == "pieces":
            if not self.exporter.running and self.cuts.markers and length:
                self._save_pieces(Path(self.engine.path), self.edit_bar.lossless)
            return
        if self.exporter.running or not self.cuts.has_cuts or not length:
            return
        segments = self.cuts.kept(length)
        if not segments:
            return

        src = Path(self.engine.path)
        lossless = self.edit_bar.lossless
        if mode == "replace":
            if not dialogs.ask(self, tr("Сохранить с удалением?"),
                               tr("Файл «{name}» будет заменён обрезанной версией. Старое видео отправится "
                                  "в корзину Windows — при необходимости его можно оттуда восстановить.", name=src.name),
                               tr("Заменить файл"), danger=True):
                return
            # Новый файл сначала собирается рядом под временным именем; исходник трогаем только
            # после успешного сохранения и проверки.
            dst = str(src.with_name(f"~{src.stem}.обрезка{src.suffix}"))
            position = self.cuts.map_to_result(self.engine.time(), length)
            self._pending_replace = (str(src), dst, position)
        else:
            # Тот же формат, что у исходника: так видео и звук можно скопировать без перекодирования.
            suffix = src.suffix
            default = src.with_name(tr("{stem} (обрезано)", stem=src.stem) + suffix)
            filters = tr("Тот же формат (*{suffix});;MP4 (*.mp4);;MKV (*.mkv);;Все файлы (*)", suffix=suffix)
            dst, _ = QFileDialog.getSaveFileName(self, tr("Сохранить как копию"), str(default), filters)
            if not dst:
                return
            if Path(dst).resolve() == src.resolve():
                dialogs.info(self, tr("Это тот же файл"), tr("Чтобы заменить исходное видео обрезанным, выберите "
                                                            "«Сохранить с удалением» в меню ▾ у кнопки сохранения."))
                return
            self._pending_replace = None

        self.edit_bar.set_exporting(True)
        self.exporter.start(str(src), dst, segments, lossless, self.prefs.get("encoder"),
                            self.edit_bar.tracks_button.selection)
        self._refresh_editor()

    def _finish_replace(self, src: str, new_file: str, position_ms: int) -> str:
        """Ставит новый файл на место исходного; исходный — в корзину. Возвращает путь итогового файла."""
        self.engine.close_file()  # mpv держит исходный файл открытым — Windows не даст его переместить
        moved = False
        for _ in range(40):  # mpv закрывает файл не мгновенно — пробуем до 2 секунд
            if QFile.moveToTrash(src):
                moved = True
                break
            QThread.msleep(50)
        if moved:
            os.replace(new_file, src)
            final = src
        else:
            # Исходник не удалось убрать — не теряем результат: оставляем его рядом обычной копией.
            final = str(Path(src).with_name(tr("{stem} (обрезано)", stem=Path(src).stem) + Path(src).suffix))
            os.replace(new_file, final)
        self._cuts_dirty = False
        self.open_file(final, position_ms)
        if not moved:
            dialogs.error(self, tr("Не удалось убрать исходный файл"),
                          tr("Возможно, он занят другой программой. Обрезанное видео сохранено рядом:"),
                          note=final)
        return final

    def _on_export_finished(self, ok: bool, message: str, note: str):
        self.edit_bar.set_exporting(False)
        self._refresh_editor()
        pending, self._pending_replace = getattr(self, "_pending_replace", None), None
        pieces, self._pending_pieces = getattr(self, "_pending_pieces", False), False
        if ok and pieces:
            self._cuts_dirty = False
            paths = message.split("\n")
            if dialogs.saved_files(self, paths, note):
                start_outside(["explorer", "/select,", str(Path(paths[0]))])
            return
        if ok and pending:
            src, new_file, position = pending
            try:
                final = self._finish_replace(src, new_file, position)
            except OSError as error:
                dialogs.error(self, tr("Не удалось заменить исходный файл"),
                              tr("Видео сохранено, но заменить исходный файл не удалось: {error}", error=error),
                              note=tr("Обрезанное видео лежит здесь:") + f"\n{new_file}")
                return
            if dialogs.saved(self, final, tr("Старое видео — в корзине Windows.") + f"\n\n{note}",
                             title=tr("Файл заменён обрезанной версией")):
                start_outside(["explorer", "/select,", str(Path(final))])
            return
        if ok:
            self._cuts_dirty = False
            if dialogs.saved(self, message, note):
                start_outside(["explorer", "/select,", str(Path(message))])
        elif message != CANCELLED:
            dialogs.error(self, tr("Не удалось сохранить видео"), message)

    def _confirm_discard_cuts(self) -> bool:
        if not (self.cuts.has_cuts and self._cuts_dirty):
            return True
        return dialogs.ask(self, tr("Обрезка не сохранена"),
                           tr("Если продолжить, разрезы и пометки этого видео пропадут."), tr("Продолжить без сохранения"))

    # --- Сведения о видео ---------------------------------------------------

    def _toggle_info(self, anchor: TitleCapsule):
        """Щелчок по капсуле с именем файла: открыть / закрыть сведения о видео под ней."""
        if self.info_panel.isVisible():
            self.info_panel.close()
            return
        if not self.engine.has_media:
            return
        self.info_panel.set_info(self.media_info.path, self.media_info.groups)
        self._info_anchor = anchor
        anchor.set_open(True)
        self.info_panel.show_under(anchor)

    def _on_media_info_ready(self, path: str):
        if path == self.media_info.path:
            self.edit_bar.tracks_button.set_tracks(self.media_info.tracks)  # «Звук: 3 из 3» — если дорожек > 1
        if self.info_panel.isVisible() and path == self.media_info.path:
            self.info_panel.set_info(path, self.media_info.groups)

    def _on_info_closed(self):
        if self._info_anchor is not None:
            self._info_anchor.set_open(False)
            self._info_anchor = None
        if self.isFullScreen():
            self._idle_timer.start()  # панель и имя спрячутся, как обычно, если мышь не двигают

    # --- Полноэкранный режим ----------------------------------------------

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._was_maximized = self.isMaximized()
            self.title_bar.hide()
            self.chrome.set_fullscreen(True)
            self.showFullScreen()
            self.controls.set_fullscreen(True)
            # Видео — на весь экран, панель — отдельным слоем поверх него.
            self.centralWidget().layout().removeWidget(self.controls_holder)
            self.floating_panel.attach(self.controls_holder, self.screen().geometry())
            if self.engine.has_media:
                self.fs_title_panel.attach(self.fs_title, self.screen().geometry())
                self._fs_title_attached = True
            self._last_cursor_pos = QCursor.pos()
            self._cursor_poll.start()
            self._idle_timer.start()

    def _exit_fullscreen(self):
        if not self.isFullScreen():
            return
        self._cursor_poll.stop()
        self._idle_timer.stop()
        self.info_panel.close()
        self.floating_panel.detach(self.controls_holder)
        if self._fs_title_attached:
            self.fs_title_panel.detach(self.fs_title)
            self._fs_title_attached = False
        self.controls_holder.setParent(self.centralWidget())
        self.centralWidget().layout().addWidget(self.controls_holder)
        self.controls_holder.slide(True, animated=False)
        self.controls_holder.show()
        self.title_bar.show()
        if getattr(self, "_was_maximized", False):
            self.showMaximized()
        else:
            self.showNormal()
        self.chrome.set_fullscreen(False)
        self.controls.set_fullscreen(False)

    # --- Окно ---------------------------------------------------------------

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" and getattr(self, "chrome", None) is not None:
            handled, result = self.chrome.handle(message)
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def changeEvent(self, event):
        if getattr(self, "chrome", None) is None:  # окно ещё строится
            super().changeEvent(event)
            return
        if event.type() == QEvent.Type.WindowStateChange:
            self.title_bar.set_maximized(self.isMaximized())
            self._update_resize_margins()
        elif event.type() == QEvent.Type.ActivationChange:
            self.title_bar.set_active(self.isActiveWindow())
        super().changeEvent(event)

    def _update_resize_margins(self):
        side = 0 if (self.isMaximized() or self.isFullScreen()) else WindowChrome.RESIZE_BORDER
        self.video_area.layout().setContentsMargins(side, 0, side, 0)

    def _poll_cursor(self):
        pos = QCursor.pos()
        if pos != self._last_cursor_pos:
            self._last_cursor_pos = pos
            if self._hold_rate is not None:
                return  # мышь двигают, чтобы менять скорость, — панель не показываем
            self._show_controls(True)
            self._idle_timer.start()

    def _hide_controls_if_idle(self):
        if not self.isFullScreen():
            return
        # Пока курсор над панелью или именем файла, открыт редактор или сведения о видео, панель не прячется.
        if self._editing or self.info_panel.isVisible():
            self._idle_timer.start()
            return
        cursor = QCursor.pos()
        over_controls = self.controls_holder.rect().contains(self.controls_holder.mapFromGlobal(cursor))
        over_title = self._fs_title_attached and self.fs_title.rect().contains(self.fs_title.mapFromGlobal(cursor))
        if over_controls or over_title:
            self._idle_timer.start()
        else:
            self._show_controls(False)

    def _show_controls(self, show: bool):
        """Показать / спрятать панель: во весь экран она — слой поверх видео, иначе — часть окна."""
        if self.isFullScreen() and self.controls_holder.window() is self.floating_panel:
            self.floating_panel.slide(show)
            if self._fs_title_attached:
                self.fs_title_panel.slide(show)
        else:
            self.controls_holder.slide(show)

    # --- Темы -------------------------------------------------------------

    def apply_theme(self, theme_id: str):
        if theme_id not in self.themes:
            theme_id = DEFAULT_THEME if DEFAULT_THEME in self.themes else next(iter(self.themes))
        theme = self.themes[theme_id]
        self.setStyleSheet(build_stylesheet(theme))
        anim_button.set_theme(theme, icon_font())
        icon = make_app_icon(theme["accent"], theme["accent_hover"])
        self.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)
        self.title_bar.set_icon(icon)
        self.chrome.set_border_color(theme["border"])
        self.controls.timeline.set_colors(theme["surface2"], theme["accent"], theme["text"],
                                          theme.get("danger", "#e5484d"), theme["text_dim"], theme["surface"])
        self.edit_bar.set_tips_colors(theme["surface"], theme["border"])
        self.edit_bar.tracks_button.set_theme(theme)
        self.info_panel.set_colors(theme["surface"], theme["border"], int(theme.get("radius", 8)))
        self.speed_overlay.set_theme(theme)
        self.message_overlay.set_theme(theme)
        dialogs.set_theme(theme)
        base_action = self.theme_actions.get(self.prefs.get("custom_base"))
        if base_action is not None:
            base_action.setChecked(True)
        self.settings.setValue("theme", theme_id)
        self._theme_id = theme_id
        if self.settings_window is not None:
            self.settings_window.set_theme(theme_id, theme, icon)
        if self.hotkeys_window is not None:
            self.hotkeys_window.set_theme(theme, icon)

    # --- Настройки --------------------------------------------------------

    def preview_frame(self) -> QImage | None:
        """Кадр открытого видео для предпросмотра уведомлений (снимок области видео с экрана, без чёрных полей)."""
        if not self.engine.has_media or not self.engine.has_video() or not self.isVisible() or self.isMinimized():
            return None
        frame = self.video_frame
        origin = frame.mapToGlobal(QPoint(0, 0))
        image = self.screen().grabWindow(0, origin.x(), origin.y(), frame.width(), frame.height()).toImage()
        # Чёрные поля по краям (видео не той формы, что окно) — обрезать: в предпросмотре нужна картинка.
        dark = lambda x, y: QColor(image.pixel(x, y)).lightness() < 10  # noqa: E731
        left, right = 0, image.width() - 1
        mid = image.height() // 2
        while left < right and dark(left, mid):
            left += 1
        while right > left and dark(right, mid):
            right -= 1
        if right - left < 40:
            return None
        return image.copy(left, 0, right - left + 1, image.height())

    def show_settings(self, page: int | None = None):
        shot = None if self.settings_window is not None and self.settings_window.isVisible() else self.preview_frame()
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self, self.prefs, self.themes, lambda: self._theme_id)
            theme = self.themes[self._theme_id]
            self.settings_window.set_theme(self._theme_id, theme, make_app_icon(theme["accent"], theme["accent_hover"]))
            # По центру окна плеера.
            frame = self.frameGeometry()
            size = self.settings_window.size()
            self.settings_window.move(frame.center().x() - size.width() // 2, frame.center().y() - size.height() // 2)
        if shot is not None or not self.engine.has_media:
            self.settings_window.preview.set_frame(shot)  # снимок — до показа окна настроек (оно бы его закрыло)
        if page is not None:
            self.settings_window.open_page(page)
        self.settings_window.show()
        bring_to_front(self.settings_window)

    def _apply_pref(self, key: str):
        """Настройка поменялась (или запуск) — применить к плееру."""
        value = self.prefs.get(key)
        if key == "window_outline":
            self.title_bar.set_outline(None if value == "none" else value)
        elif key == "show_stop":
            self.controls.set_stop_visible(value)
        elif key == "seek_step":
            self.controls.set_seek_step(value)
        elif key == "end_action":
            # «Повтор» — то же, что кнопка повтора (L) и пункт в шестерёнке.
            if value != "repeat":
                self._end_action_before_repeat = value
            action = self.controls.repeat_action
            action.blockSignals(True)
            action.setChecked(value == "repeat")
            action.blockSignals(False)
            self.engine.set_loop(value == "repeat")
        elif key == "export_quality":
            self.edit_bar.set_lossless(value == "lossless")
        elif key == "save_mode":
            self.edit_bar.save_button.set_mode(value)
        elif key.startswith("custom_"):
            self.themes[CUSTOM_THEME] = self._custom_theme()
            if self._theme_id == CUSTOM_THEME:
                self.apply_theme(CUSTOM_THEME)
        elif key == "resume" and not value:
            self.settings.remove("positions")  # выключили — забыть все места

    def _custom_theme(self) -> dict:
        """«Своя» тема из настроек: основа + цвет интерфейса + цвет уведомлений."""
        base = self.themes.get(self.prefs.get("custom_base")) or self.themes[DEFAULT_THEME]
        accent = self.prefs.get("custom_accent")
        shade = self.prefs.get("custom_notify")
        notify = self.prefs.get("custom_notify_color") if shade == "own" else notify_shade(accent, shade)
        return build_custom_theme(base, accent, notify)

    # --- Продолжение с места остановки и конец видео ----------------------

    @staticmethod
    def _position_key(path: str) -> str:
        return "positions/" + hashlib.sha1(str(Path(path).resolve()).lower().encode("utf-8")).hexdigest()[:20]

    def _saved_position(self, path: str) -> int:
        try:
            return max(int(str(self.settings.value(self._position_key(path), "0")).split(";")[0]), 0)
        except ValueError:
            return 0

    def _remember_position(self):
        """Запомнить, где остановились в открытом видео (для «Продолжать с места, где остановились»)."""
        if not self.prefs.get("resume") or not self.engine.has_media or self.engine.is_error():
            return
        key = self._position_key(self.engine.path)
        position, length = self.engine.time(), self.engine.length()
        if self.engine.is_ended() or not length or not RESUME_MIN_MS <= position <= length - RESUME_END_MARGIN_MS:
            self.settings.remove(key)  # начало или досмотрено — в следующий раз сначала
            return
        self.settings.setValue(key, f"{position};{int(time.time())}")
        self.settings.beginGroup("positions")
        names = self.settings.childKeys()
        if len(names) > RESUME_MAX_FILES:  # самые давние — забыть
            def stamp(name):
                try:
                    return int(str(self.settings.value(name)).split(";")[1])
                except (IndexError, ValueError):
                    return 0
            for name in sorted(names, key=stamp)[:len(names) - RESUME_MAX_FILES]:
                self.settings.remove(name)
        self.settings.endGroup()

    def _on_video_ended(self):
        self.settings.remove(self._position_key(self.engine.path))
        if self.controls.repeat_action.isChecked() or self.prefs.get("end_action") != "next":
            return
        files = self._folder_videos(Path(self.engine.path))
        names = [f.name.lower() for f in files]
        current = Path(self.engine.path).name.lower()
        if current in names and names.index(current) + 1 < len(files):
            QTimer.singleShot(0, lambda: self.step_file(1))  # не из обработчика таймера

    # --- Справка ----------------------------------------------------------

    def _show_hotkeys(self):
        """Окно «Горячие клавиши» (hotkeys_window.py): по центру окна плеера, с текущими шагами из настроек."""
        if self.hotkeys_window is None:
            self.hotkeys_window = HotkeysWindow(self, self.prefs)
            theme = self.themes[self._theme_id]
            self.hotkeys_window.set_theme(theme, make_app_icon(theme["accent"], theme["accent_hover"]))
        window = self.hotkeys_window
        window.refresh()
        center = self.frameGeometry().center()
        window.move(center.x() - window.width() // 2, center.y() - window.height() // 2)
        window.show()
        bring_to_front(window)

    # --- Смена языка: перезапуск --------------------------------------------

    def offer_restart(self, lang: str, parent=None):
        """Язык сменили в настройках: спросить (уже на новом языке), перезапустить ли плеер сейчас."""
        if dialogs.ask(parent or self, tr_in(lang, "Перезапустить плеер?"),
                       tr_in(lang, "Язык сменится после перезапуска. Открытое видео продолжится с того же места."),
                       tr_in(lang, "Перезапустить"), tr_in(lang, "Позже")):
            self.restart()

    def restart(self):
        """Закрыть плеер как обычно (с вопросами о несохранённом) и запустить заново с тем же видео и местом.
        Новый процесс запускает main.py — после того как этот закроет канал «одного окна»."""
        if FROZEN:
            command = [sys.executable]
        else:
            command = [str(registration.pythonw_path()), str(APP_DIR / "main.py")]
        if self.engine.has_media and not self.engine.is_error():
            command += [self.engine.path, f"--start-ms={self.engine.time()}"]
        self.restart_command = command
        if not self.close():  # отказались закрывать (идёт сохранение, несохранённая обрезка)
            self.restart_command = None

    # --- Закрытие ---------------------------------------------------------

    def closeEvent(self, event):
        if self.exporter.running:
            if not dialogs.ask(self, tr("Идёт сохранение видео"), tr("Если выйти сейчас, сохранение прервётся."),
                               tr("Прервать и выйти"), danger=True):
                event.ignore()
                return
            self.exporter.cancel()
        elif not self._confirm_discard_cuts():
            event.ignore()
            return
        self.timer.stop()
        if not self.isFullScreen():
            self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("volume", self.engine.volume)
        self._remember_position()
        for window in (self.settings_window, self.hotkeys_window):
            if window is not None:
                window.close()
        self.engine.release()
        super().closeEvent(event)
