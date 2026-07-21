"""Genera firmador.ico para PyInstaller / instalador. Ejecutar antes del build."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path


def build() -> None:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((10, 10, size - 10, size - 10), fill=(21, 101, 192, 255))
    try:
        font = ImageFont.truetype("segoeui.ttf", 150)
    except OSError:
        font = ImageFont.load_default()
    d.text((size / 2, size / 2), "F", fill="white", font=font, anchor="mm")

    out = Path(__file__).parent / "firmador.ico"
    img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Icono escrito: {out}")


if __name__ == "__main__":
    build()
