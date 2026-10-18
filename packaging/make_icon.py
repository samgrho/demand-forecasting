"""Draw the app icon (a small ascending bar chart, in the dashboard's level colours)."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).with_name("app.ico")
SIZE = 256
BACKGROUND = "#13233b"
BARS = [("#86b6ef", 0.42), ("#5598e7", 0.62), ("#256abf", 0.50), ("#9ec5f4", 0.86)]


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=52, fill=BACKGROUND)
    left, right, base, top = 46, SIZE - 46, SIZE - 50, 52
    gap = 14
    width = (right - left - gap * (len(BARS) - 1)) / len(BARS)
    for i, (colour, height) in enumerate(BARS):
        x0 = left + i * (width + gap)
        y0 = base - (base - top) * height
        d.rounded_rectangle((x0, y0, x0 + width, base), radius=10, fill=colour)
        d.rectangle((x0, base - 12, x0 + width, base), fill=colour)  # square at the baseline
    return img


if __name__ == "__main__":
    draw().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {OUT}")
