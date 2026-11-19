"""Генерация иконки веб-панели (favicon) — единый источник геометрии.

Запуск: ./run.sh favicon  (или python3 scripts/40_favicon.py)
Результат: web/static/img/favicon.svg, favicon.ico, favicon-32.png, apple-touch-icon.png

Мотив повторяет логотип панели: градиентная плитка 135° (#4f7cff → #8a5cff)
и белая восходящая линия графика.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "web" / "static" / "img"
S = 1024                      # рабочее разрешение (суперсэмплинг)

C1 = (0x4F, 0x7C, 0xFF)
C2 = (0x8A, 0x5C, 0xFF)
PTS = [(13, 44), (25, 31), (36, 37), (51, 19)]   # сетка 64x64
STROKE = 5.6                  # толщина линии в той же сетке
RADIUS = 15                   # скругление плитки

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Autopilot">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#4f7cff"/>
      <stop offset="1" stop-color="#8a5cff"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="{radius}" fill="url(#g)"/>
  <polyline points="{pts}" fill="none" stroke="#fff" stroke-width="{stroke}"
            stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def gradient(size):
    n = 512
    buf = bytearray(n * n * 3)
    k = 1.0 / (2 * (n - 1))
    for y in range(n):
        row = y * n * 3
        for x in range(n):
            t = (x + y) * k
            i = row + x * 3
            buf[i] = int(C1[0] + (C2[0] - C1[0]) * t)
            buf[i + 1] = int(C1[1] + (C2[1] - C1[1]) * t)
            buf[i + 2] = int(C1[2] + (C2[2] - C1[2]) * t)
    img = Image.frombytes("RGB", (n, n), bytes(buf)).convert("RGBA")
    return img.resize((size, size), Image.BICUBIC)


def render(rounded=True, size=S):
    """Плитка с линией. rounded=False — полноразмерный квадрат (для iOS)."""
    base = gradient(size)
    if rounded:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, size - 1, size - 1], radius=RADIUS * size / 64, fill=255
        )
        base.putalpha(mask)

    k = size / 64
    pts = [(x * k, y * k) for x, y in PTS]
    w = STROKE * k

    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.line(pts, fill="white", width=round(w), joint="curve")
    for px, py in pts:                       # круглые концы и стыки
        d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill="white")
    return Image.alpha_composite(base, layer)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    icon = render()

    svg = SVG.format(
        radius=RADIUS,
        stroke=STROKE,
        pts=" ".join(f"{x},{y}" for x, y in PTS),
    )
    (OUT / "favicon.svg").write_text(svg, encoding="utf-8")

    icon.resize((32, 32), Image.LANCZOS).save(OUT / "favicon-32.png")
    icon.save(OUT / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    render(rounded=False).resize((180, 180), Image.LANCZOS).save(
        OUT / "apple-touch-icon.png"
    )
    print(f"favicon: svg, ico (16/32/48), 32 png, apple-touch 180 -> {OUT}")


if __name__ == "__main__":
    main()
