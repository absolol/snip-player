# Сборка PyInstaller (одна папка, без консоли). Запускает её build.py — вручную не нужно.
# Qt берём только то, что плеер использует: QtCore, QtGui, QtWidgets, QtSvg, QtNetwork (QLocalServer).

from pathlib import Path

ROOT = Path(SPECPATH).parent

# Модули Qt, которых плеер не импортирует, — чтобы PyInstaller не тащил их по цепочке.
QT_EXCLUDES = [
    f"PySide6.{name}" for name in (
        "QtQml", "QtQuick", "QtQuickWidgets", "QtQuickControls2", "QtOpenGL", "QtOpenGLWidgets", "QtPrintSupport",
        "QtSql", "QtTest", "QtXml", "QtDBus", "QtConcurrent", "QtHelp", "QtDesigner", "QtUiTools", "QtSvgWidgets",
        "QtMultimedia", "QtMultimediaWidgets", "QtWebEngineCore", "QtWebEngineWidgets", "QtCharts", "QtPdf",
    )
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "themes" / "*.json"), "themes"),
        (str(ROOT / "themes" / "style.qss"), "themes"),
        (str(ROOT / "lib" / "libmpv-2.dll"), "lib"),
    ],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtNetwork"],
    # ssl / _hashlib тянут OpenSSL (~12 МБ): сеть плееру не нужна, sha1 для мест просмотра есть и без OpenSSL.
    excludes=["tkinter", "unittest", "pydoc", "doctest", "pdb", "xmlrpc", "sqlite3", "lib2to3", "ssl", "_ssl",
              "_hashlib", *QT_EXCLUDES],
    noarchive=False,
)

# Из плагинов Qt нужны: окно Windows (qwindows), родной стиль, JPG для скриншотов в JPG.
# Иконки и SVG плеер рисует сам (QSvgRenderer), PNG Qt умеет без плагинов.
KEEP_PLUGINS = {"qwindows.dll", "qmodernwindowsstyle.dll", "qjpeg.dll"}


def _needed(dest: str) -> bool:
    d = dest.replace("\\", "/")
    name = d.rsplit("/", 1)[-1]
    if "/plugins/" in d:
        return name in KEEP_PLUGINS
    if "/translations/" in d:  # переводы Qt не используются: файловые окна — родные окна Windows
        return False
    if name in ("opengl32sw.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll", "libcrypto-3.dll", "libssl-3.dll", "Qt6Pdf.dll", "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlMeta.dll",
                "Qt6QmlWorkerScript.dll", "Qt6Quick.dll", "Qt6OpenGL.dll", "Qt6VirtualKeyboard.dll"):
        return False
    return True


a.binaries = [b for b in a.binaries if _needed(b[0])]
a.datas = [d for d in a.datas if _needed(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Snip Player",
    icon=str(ROOT / "Snip Player.ico"),
    console=False,
    upx=False,
    version=None,
)

coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="Snip Player")
