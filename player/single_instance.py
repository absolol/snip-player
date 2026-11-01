"""Режим «одно окно»: второй запуск плеера передаёт файл уже открытому окну и выходит.

Работающий плеер слушает локальный канал (QLocalServer — именованный канал Windows,
имя своё у каждого пользователя). Второй запуск подключается, отправляет строку JSON
{"cmd": "open", "path": ...} или {"cmd": "show"} и ждёт ответ «ok». Нет ответа за
REPLY_TIMEOUT_MS — первый плеер завис или закрывается, второй запускается сам.

Проверку и запуск сервера охраняет системный мьютекс: если Проводник запускает плеер
для нескольких файлов сразу, окно всё равно откроется одно.
"""

import ctypes
import getpass
import hashlib
import json
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QDeadlineTimer, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

CONNECT_TIMEOUT_MS = 500
REPLY_TIMEOUT_MS = 3000
MUTEX_TIMEOUT_MS = 5000

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_user32.AllowSetForegroundWindow.argtypes = (wintypes.DWORD,)
for _name in ("IsIconic", "SetForegroundWindow", "BringWindowToTop"):
    getattr(_user32, _name).argtypes = (wintypes.HWND,)
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.c_void_p)
_user32.AttachThreadInput.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.BOOL)
_ASFW_ANY = 0xFFFFFFFF


def _base_name() -> str:
    # Имя пользователя бывает кириллицей — в имени канала оставляем только хеш.
    user = hashlib.sha1(getpass.getuser().lower().encode("utf-8")).hexdigest()[:12]
    return f"Proigryvatel.Player.{user}"


SERVER_NAME = _base_name()


class _StartupLock:
    """Именованный мьютекс Windows на время «проверить — запустить сервер»."""

    def __init__(self, name: str):
        self._handle = _kernel32.CreateMutexW(None, False, f"Local\\{name}.startup")
        self._owned = False

    def __enter__(self):
        if self._handle:
            # WAIT_OBJECT_0 = 0, WAIT_ABANDONED = 0x80 (прошлый владелец упал) — мьютекс наш в обоих случаях.
            self._owned = _kernel32.WaitForSingleObject(self._handle, MUTEX_TIMEOUT_MS) in (0, 0x80)
        return self

    def __exit__(self, *exc):
        if self._handle:
            if self._owned:
                _kernel32.ReleaseMutex(self._handle)
            _kernel32.CloseHandle(self._handle)
            self._handle = None


def _send(message: dict, server_name: str) -> bool:
    """Передать команду работающему плееру. True — он ответил и всё сделает сам."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        return False
    # Окно, которое запустил щелчок в Проводнике, вправе забрать фокус; разрешаем это
    # первому плееру — иначе Windows лишь мигнёт его кнопкой на панели задач.
    _user32.AllowSetForegroundWindow(_ASFW_ANY)
    socket.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    deadline = QDeadlineTimer(REPLY_TIMEOUT_MS)  # на запись и ответ вместе
    socket.waitForBytesWritten(max(deadline.remainingTime(), 0))
    reply = b""
    while b"\n" not in reply and not deadline.hasExpired() and socket.waitForReadyRead(deadline.remainingTime()):
        reply += bytes(socket.readAll())
    socket.abort()
    return reply.strip() == b"ok"


class InstanceServer(QObject):
    """Сервер в работающем плеере. Сигналы: open_requested(путь), show_requested()."""

    open_requested = Signal(str)
    show_requested = Signal()

    def __init__(self, server_name: str = SERVER_NAME, parent=None):
        super().__init__(parent)
        self._server = QLocalServer(self)
        # Только текущий пользователь (на Windows — ACL канала).
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)
        self.listening = self._server.listen(server_name)

    def close(self):
        self._server.close()

    def _on_new_connection(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setProperty("buffer", b"")
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(socket.deleteLater)

    def _on_ready_read(self, socket: QLocalSocket):
        data = socket.property("buffer") + bytes(socket.readAll())
        if b"\n" not in data:
            socket.setProperty("buffer", data)
            return
        line = data.split(b"\n", 1)[0]
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            message = {}
        socket.write(b"ok\n")
        socket.flush()
        socket.disconnectFromServer()
        # Сигналы — после ответа: открытие файла может показать вопрос и ждать человека.
        if message.get("cmd") == "open" and message.get("path"):
            self.open_requested.emit(str(message["path"]))
        else:
            self.show_requested.emit()


def hand_over_or_listen(path: str | None, server_name: str = SERVER_NAME) -> InstanceServer | None:
    """None — плеер уже запущен и получил команду (этому запуску пора выйти).
    Иначе — сервер для этого запуска (может и не слушать, если канал занят зависшим плеером)."""
    message = {"cmd": "open", "path": str(Path(path).resolve())} if path else {"cmd": "show"}
    with _StartupLock(server_name):
        if _send(message, server_name):
            return None
        return InstanceServer(server_name)


def bring_to_front(window):
    """Поднять окно: развернуть из свёрнутого (в прежнее состояние) и забрать фокус."""
    hwnd = int(window.winId())
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE — вернёт и развёрнутое состояние
    window.raise_()
    window.activateWindow()
    if (_user32.GetForegroundWindow() or 0) == hwnd:
        return
    if not _user32.SetForegroundWindow(hwnd):
        # Запасной приём: на миг «присоединиться» к потоку окна, у которого сейчас фокус.
        foreground = _user32.GetForegroundWindow()
        other = _user32.GetWindowThreadProcessId(foreground, None)
        mine = _kernel32.GetCurrentThreadId()
        if other and other != mine and _user32.AttachThreadInput(mine, other, True):
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
            _user32.AttachThreadInput(mine, other, False)
