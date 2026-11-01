"""Иконки панели: Lucide (lucide.dev, ISC) и их анимации в духе Lucide Animated (lucide-animated.com, MIT).

Лицензии — в папке licenses/. Каждая часть иконки — маленький SVG-фрагмент в системе 24×24: так части
можно двигать, поворачивать и проявлять по отдельности. Движение — пружины (лёгкий перелёт и успокоение,
как type: "spring" в Motion) и короткие «рывки» по ключевым кадрам.

Функция иконки: paint(p, color, motion, now, **options); painter p уже переведён в систему 24×24.
"""

from collections import OrderedDict

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtSvg import QSvgRenderer

STROKE = 1.9
SETTLE_S = 1.6  # сколько после наведения / ухода мыши иконку ещё нужно перерисовывать (мягкая пружина шестерёнки)


# --- Движение -------------------------------------------------------------

def _ease_in_out(u: float) -> float:
    return u * u * (3 - 2 * u)


def keyframes(t, values, times, duration: float) -> float:
    """Ключевые кадры (как массив значений в Motion), между кадрами — плавно. t=None — покой (первый кадр)."""
    if t is None or t <= 0:
        return values[0]
    u = min(t / duration, 1.0)
    for i in range(len(times) - 1):
        if u <= times[i + 1]:
            span = times[i + 1] - times[i]
            k = 0 if span == 0 else (u - times[i]) / span
            return values[i] + (values[i + 1] - values[i]) * _ease_in_out(k)
    return values[-1]


class Motion:
    """Наведение на одну кнопку: время входа мыши и пружины (каждая со своей жёсткостью)."""

    _STEP = 1 / 240

    def __init__(self):
        self.enter_t = None   # когда навели (None — мышь не над кнопкой)
        self._springs = {}    # (жёсткость, затухание) → [положение, скорость, время]

    def enter(self, now: float):
        self._catch_up(now)
        self.enter_t = now

    def leave(self, now: float):
        self._catch_up(now)
        self.enter_t = None

    def _catch_up(self, now: float):
        # Пружины считаются при перерисовке. Если кнопку не перерисовывали (окно свёрнуто, панель спрятана),
        # досчитать их до этого момента со старой целью — иначе со следующего раза пружина «залипала».
        for stiffness, damping in list(self._springs):
            self.amount(now, stiffness, damping)

    def reset(self):
        self.enter_t = None
        self._springs.clear()

    @property
    def hovered(self) -> bool:
        return self.enter_t is not None

    def since_enter(self, now: float):
        """Секунды с наведения или None, если мышь не над кнопкой."""
        return None if self.enter_t is None else now - self.enter_t

    def amount(self, now: float, stiffness: float, damping: float) -> float:
        """Пружина 0 → 1 (наведено) и обратно; если мышь вернулась на полпути — продолжает с того же места."""
        target = 1.0 if self.hovered else 0.0
        state = self._springs.get((stiffness, damping))
        if state is None:
            state = self._springs[(stiffness, damping)] = [0.0, 0.0, now]
        x, v, last = state
        dt = max(now - last, 0.0)
        if dt > 3.0:  # давно не считали — пружина давно успокоилась
            x, v, dt = target, 0.0, 0.0
        while dt > 0:
            h = min(self._STEP, dt)
            v += (-stiffness * (x - target) - damping * v) * h
            x += v * h
            dt -= h
        if abs(x - target) < 1e-4 and abs(v) < 1e-3:
            x, v = target, 0.0
        state[:] = [x, v, now]
        return x


# --- Рисование частей -----------------------------------------------------

_cache: "OrderedDict[tuple, QSvgRenderer]" = OrderedDict()
_CACHE_SIZE = 800


def _quantize(color: QColor) -> QColor:
    # Цвет при наведении плавно меняется; округление (незаметное глазу) не даёт плодить тысячи копий SVG.
    q = lambda v: min(255, round(v / 6) * 6)  # noqa: E731
    return QColor(q(color.red()), q(color.green()), q(color.blue()))


def part(p: QPainter, svg: str, color: QColor, opacity: float = 1.0, fill: bool = False):
    """Нарисовать SVG-фрагмент в системе 24×24."""
    color = _quantize(color)
    key = (svg, color.rgb(), fill)
    renderer = _cache.get(key)
    if renderer is None:
        c = color.name()
        paint = f'fill="{c}" stroke="{c}"' if fill else f'fill="none" stroke="{c}"'
        doc = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {paint} stroke-width="{STROKE}" '
               f'stroke-linecap="round" stroke-linejoin="round">{svg}</svg>')
        renderer = QSvgRenderer(QByteArray(doc.encode()))
        _cache[key] = renderer
        if len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    if opacity <= 0:
        return
    p.save()
    p.setOpacity(p.opacity() * opacity)
    renderer.render(p, QRectF(0, 0, 24, 24))
    p.restore()


def _around(p: QPainter, cx: float, cy: float, angle: float):
    p.translate(cx, cy)
    p.rotate(angle)
    p.translate(-cx, -cy)


# --- Иконки ---------------------------------------------------------------

def pin(p, color, m, now, **_):
    # как map-pin: подпрыгивает (0 → −3 → −2) и держится приподнятой; иголка дорисовывается
    t = m.since_enter(now)
    lift = keyframes(t, [0, -3.2, -2], [0, 0.6, 1], 0.5) if t is not None else -2 * m.amount(now, 250, 25)
    if t is not None:
        m.amount(now, 250, 25)  # пружина «ухода» стартует с поднятого положения
    p.save()
    p.translate(0, lift)
    part(p, '<path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1'
            'v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 '
            '1 1 0 0 1 1 1z"/>', color)
    p.restore()
    needle = 1.0 if t is None else min(max((t - 0.25) / 0.3, 0.0), 1.0)
    if needle > 0:
        p.save()
        p.setClipRect(QRectF(0, 16, 24, 1 + 6 * needle))
        part(p, '<path d="M12 17v5"/>', color)
        p.restore()


def _skip(p, color, m, now, forward):
    # как chevron-first: треугольник «подаётся» −2 → 1 → −1 → 0
    t = m.since_enter(now)
    dx = keyframes(t, [-2, 1, -1, 0], [0, 0.3, 0.7, 1], 0.6) * (-1 if forward else 1) if t is not None else 0
    p.save()
    p.translate(dx, 0)
    if forward:
        part(p, '<path d="M6.029 4.285A2 2 0 0 0 3 6v12a2 2 0 0 0 3.029 1.715l9.997-5.998a2 2 0 0 0 .003-3.432z"/>', color)
    else:
        part(p, '<path d="M17.971 4.285A2 2 0 0 1 21 6v12a2 2 0 0 1-3.029 1.715l-9.997-5.998a2 2 0 0 1-.003-3.432z"/>', color)
    p.restore()
    part(p, '<path d="M21 4v16"/>' if forward else '<path d="M3 20V4"/>', color)


def prev_file(p, color, m, now, **_):
    _skip(p, color, m, now, False)


def next_file(p, color, m, now, **_):
    _skip(p, color, m, now, True)


def _seek(p, color, m, now, forward, seconds):
    # как rotate-ccw / rotate-cw: стрелка проворачивается на 50° на пружине; цифра на месте
    angle = m.amount(now, 250, 25) * (50 if forward else -50)
    p.save()
    _around(p, 12, 12, angle)
    if forward:
        part(p, '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>', color)
    else:
        part(p, '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>', color)
    p.restore()
    p.setPen(color)
    font = QFont("Segoe UI")
    font.setPixelSize(9)
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(6, 6.5, 12, 12), Qt.AlignmentFlag.AlignCenter, str(seconds))


def seek_back(p, color, m, now, seconds=5, **_):
    _seek(p, color, m, now, False, seconds)


def seek_forward(p, color, m, now, seconds=5, **_):
    _seek(p, color, m, now, True, seconds)


def play(p, color, m, now, **_):
    # как play: короткий толчок x 0 → −1 → 2 → 0 и наклон 0 → −10° → 0
    t = m.since_enter(now)
    dx = keyframes(t, [0, -1, 2, 0], [0, 0.2, 0.5, 1], 0.5)
    rot = keyframes(t, [0, -10, 0, 0], [0, 0.2, 0.5, 1], 0.5)
    p.save()
    p.translate(dx, 0)
    _around(p, 12, 12, rot)
    part(p, '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>',
         color, fill=True)
    p.restore()


def pause(p, color, m, now, **_):
    # как pause: полоски по очереди «кивают» вниз
    t = m.since_enter(now)
    for x, values in ((5, [0, 2, 0, 0]), (14, [0, 0, 2, 0])):
        p.save()
        p.translate(0, keyframes(t, values, [0, 0.2, 0.5, 1], 0.5))
        part(p, f'<rect x="{x}" y="3" width="5" height="18" rx="1"/>', color, fill=True)
        p.restore()


def _chevron(p, color, m, now, forward):
    # как chevron-left / right: 0 → ∓2 → 0 за 0,5 с
    t = m.since_enter(now)
    p.save()
    p.translate(keyframes(t, [0, 2 if forward else -2, 0], [0, 0.4, 1], 0.5), 0)
    part(p, '<path d="m9 18 6-6-6-6"/>' if forward else '<path d="m15 18-6-6 6-6"/>', color)
    p.restore()


def frame_back(p, color, m, now, **_):
    _chevron(p, color, m, now, False)


def frame_forward(p, color, m, now, **_):
    _chevron(p, color, m, now, True)


def volume(p, color, m, now, muted=False, **_):
    # как volume: волны появляются по очереди (через 0,1 и 0,2 с); без звука — крестик
    t = m.since_enter(now)
    part(p, '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 '
            '1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/>', color)
    if muted:
        for d, delay in (('<path d="m16.5 14.5 5-5"/>', 0.1), ('<path d="m16.5 9.5 5 5"/>', 0.2)):
            part(p, d, color, 1.0 if t is None else min(max((t - delay) / 0.15, 0.0), 1.0))
        return
    for d, delay in (('<path d="M16 9a5 5 0 0 1 0 6"/>', 0.1), ('<path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>', 0.2)):
        part(p, d, color, 1.0 if t is None else min(max((t - delay) / 0.15, 0.0), 1.0))


def repeat(p, color, m, now, **_):
    # в духе maximize: верхняя стрелка уезжает вправо, нижняя — влево (пружина)
    a = m.amount(now, 250, 22) * 2
    p.save()
    p.translate(a, 0)
    part(p, '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/>', color)
    p.restore()
    p.save()
    p.translate(-a, 0)
    part(p, '<path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>', color)
    p.restore()


def screenshot(p, color, m, now, **_):
    # корпус чуть «нажимается», объектив «фокусируется» (1 → 0,55 → 1,15 → 1)
    t = m.since_enter(now)
    body = keyframes(t, [0, 1, 0], [0, 0.3, 1], 0.4)
    lens = keyframes(t, [1, 0.55, 1.15, 1], [0, 0.3, 0.65, 1], 0.55)
    p.save()
    p.translate(0, body * 0.8)
    part(p, '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 '
            '0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z"/>', color)
    p.translate(12, 13)
    p.scale(lens, lens)
    p.translate(-12, -13)
    part(p, '<circle cx="12" cy="13" r="3"/>', color)
    p.restore()


def cut(p, color, m, now, **_):
    # ножницы два раза «щёлкают»: половинки поворачиваются навстречу вокруг оси (12, 12)
    angle = keyframes(m.since_enter(now), [0, 26, 0, 26, 0], [0, 0.2, 0.45, 0.7, 1], 0.6)
    p.save()
    _around(p, 12, 12, -angle / 2)
    part(p, '<circle cx="6" cy="6" r="3"/><path d="M8.12 8.12 12 12"/><path d="M14.8 14.8 20 20"/>', color)
    p.restore()
    p.save()
    _around(p, 12, 12, angle / 2)
    part(p, '<circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88"/>', color)
    p.restore()


def settings(p, color, m, now, **_):
    # как settings: пол-оборота на мягкой пружине (stiffness 50, damping 10 — с перелётом)
    p.save()
    _around(p, 12, 12, m.amount(now, 50, 10) * 180)
    part(p, '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 '
            '2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 '
            '2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 '
            '6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>', color)
    p.restore()


def fullscreen(p, color, m, now, exit_mode=False, **_):
    # как maximize / minimize: уголки расходятся наружу (из полноэкранного — сходятся) на 2 px
    a = m.amount(now, 250, 25) * 2
    if exit_mode:
        corners = (('<path d="M8 3v3a2 2 0 0 1-2 2H3"/>', 1, 1), ('<path d="M21 8h-3a2 2 0 0 1-2-2V3"/>', -1, 1),
                   ('<path d="M3 16h3a2 2 0 0 1 2 2v3"/>', 1, -1), ('<path d="M16 21v-3a2 2 0 0 1 2-2h3"/>', -1, -1))
    else:
        corners = (('<path d="M8 3H5a2 2 0 0 0-2 2v3"/>', -1, -1), ('<path d="M21 8V5a2 2 0 0 0-2-2h-3"/>', 1, -1),
                   ('<path d="M3 16v3a2 2 0 0 0 2 2h3"/>', -1, 1), ('<path d="M16 21h3a2 2 0 0 0 2-2v-3"/>', 1, 1))
    for d, sx, sy in corners:
        p.save()
        p.translate(sx * a, sy * a)
        part(p, d, color)
        p.restore()


ICONS = {
    "pin": pin, "prev_file": prev_file, "next_file": next_file, "seek_back": seek_back,
    "seek_forward": seek_forward, "play": play, "pause": pause, "frame_back": frame_back,
    "frame_forward": frame_forward, "volume": volume, "repeat": repeat, "screenshot": screenshot,
    "cut": cut, "settings": settings, "fullscreen": fullscreen,
}
