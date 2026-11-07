"""Generate the original Solar Inverter Cloud Bridge mark from one vector geometry."""

from math import cos, pi, sin
from pathlib import Path
import argparse

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def image(size):
    scale = size * 4 / 256
    canvas = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    point = lambda xy: tuple(round(value * scale) for value in xy)
    background, light, gold = "#244F5A", "#F1EEE3", "#D9B775"
    draw.rounded_rectangle(point((4, 4, 252, 252)), radius=round(22 * scale), fill=background,
                           outline="#456975", width=round(2 * scale))

    def line(points, color, width):
        draw.line([point(p) for p in points], fill=color, width=round(width * scale), joint="curve")
        radius = width / 2
        for x, y in (points[0], points[-1]):
            draw.ellipse(point((x - radius, y - radius, x + radius, y + radius)), fill=color)

    draw.ellipse(point((62, 62, 138, 138)), fill=gold)
    for angle in range(0, 360, 45):
        radians = angle * pi / 180
        line([(100 + 54 * cos(radians), 100 + 54 * sin(radians)),
              (100 + 68 * cos(radians), 100 + 68 * sin(radians))], gold, 7)
    bolt = [(157, 82), (114, 151), (143, 151), (126, 222), (199, 130), (166, 130), (183, 82)]
    # A background-colored separation keeps the two shapes legible at 32 px.
    draw.line([point(p) for p in (*bolt, bolt[0])], fill=background, width=round(14 * scale), joint="curve")
    draw.polygon([point(p) for p in bolt], fill=light)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    destination = ROOT / "custom_components/solar_inverter_bridge/brand"
    destination.mkdir(exist_ok=True)
    for size, suffix in ((256, ""), (512, "@2x")):
        for name in ("icon", "logo"):
            target = destination / f"{name}{suffix}.png"
            image(size).save(target, format="PNG", optimize=True)
            print(target.relative_to(ROOT))
    if args.preview:
        preview = Image.new("RGB", (640, 320), "#F6F8FA")
        draw = ImageDraw.Draw(preview)
        draw.rectangle((320, 0, 640, 320), fill="#121A22")
        font = ImageFont.load_default(size=18)
        for offset, color, label in ((0, "#244F5A", "Light background"), (320, "#DDE5E8", "Dark background")):
            for size, top in ((128, 50), (32, 210)):
                mark = image(size)
                preview.paste(mark, (offset + (320 - size) // 2, top), mark)
            draw.text((offset + 80, 272), label, font=font, fill=color)
        preview.save(args.preview)
