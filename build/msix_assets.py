"""Gera os logos do pacote MSIX a partir de assets/icon_256.png. Uso: msix_assets.py ORIGEM.png PASTA"""
import sys
from pathlib import Path

from PIL import Image

src, dest = Path(sys.argv[1]), Path(sys.argv[2])
dest.mkdir(parents=True, exist_ok=True)
base = Image.open(src).convert("RGBA")


def square(size):
    return base.resize((size, size), Image.LANCZOS)


def wide(w, h):
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    icon = square(h)
    canvas.paste(icon, ((w - h) // 2, 0), icon)
    return canvas


square(44).save(dest / "Square44x44Logo.png")
square(88).save(dest / "Square44x44Logo.scale-200.png")
square(150).save(dest / "Square150x150Logo.png")
square(300).save(dest / "Square150x150Logo.scale-200.png")
wide(310, 150).save(dest / "Wide310x150Logo.png")
wide(620, 300).save(dest / "Wide310x150Logo.scale-200.png")
square(50).save(dest / "StoreLogo.png")
square(100).save(dest / "StoreLogo.scale-200.png")
print("logos:", ", ".join(sorted(p.name for p in dest.glob("*.png"))))
