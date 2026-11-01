"""ffmpeg / ffprobe закрываются вместе с плеером.

Плеер кладёт себя в «задание» Windows (Job Object) с флагом «закрыть всё при закрытии задания»; всё, что он
запускает, попадает туда же. Когда процесс плеера завершается (как угодно, даже аварийно), Windows закрывает
последний дескриптор задания и вместе с ним — оставшиеся ffmpeg / ffprobe. Без этого при выходе ровно в момент
запуска ffprobe тот оставался навсегда «замороженным» (создан, но не запущен; найдено 01.11.2026).

То, что должно жить дольше плеера (перезапуск после смены языка, Проводник), — start_outside().
"""

import ctypes
import subprocess
from ctypes import wintypes

BREAKAWAY = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_LIMIT_BREAKAWAY_OK = 0x00000800
_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_job = None  # дескриптор держим до конца процесса: его закрытие и закрывает ffmpeg


def close_with_player() -> bool:
    """Вызвать один раз при запуске. False — не получилось (плеер работает как раньше)."""
    global _job
    if _job is not None:
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return False
    limits = _ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = _LIMIT_KILL_ON_JOB_CLOSE | _LIMIT_BREAKAWAY_OK
    if not (kernel32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                             ctypes.byref(limits), ctypes.sizeof(limits))
            and kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())):
        kernel32.CloseHandle(job)
        return False
    _job = job
    return True


def start_outside(command, creationflags: int = 0, **kwargs) -> subprocess.Popen:
    """Запустить то, что должно пережить плеер, — вне задания. Если плеер сам запущен внутри чужого задания,
    которое не отпускает процессы (Windows отвечает «отказано в доступе»), — запустить как обычно."""
    try:
        return subprocess.Popen(command, creationflags=creationflags | BREAKAWAY, **kwargs)
    except PermissionError:
        return subprocess.Popen(command, creationflags=creationflags, **kwargs)
