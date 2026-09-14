"""Generate every Orion logo/icon file from one source image.

    uv run --no-sync python installer/make_brand_assets.py <source.png>

The source is the wide Orion logo artwork. Square icons are cropped around the
emblem in its centre; wide placements use the full artwork. Outputs:

* frontend/src-tauri/icons/*      desktop app icons (ico, icns, png sizes)
* frontend/public/*               favicon, apple-touch-icon, PWA icons
* frontend/src/assets/orion-logo.png   in-app logo (loading screen)
* assets/Orion_Circular_Logo.png, assets/Orion_Horizontal_Logo.png
* installer/windows/*.bmp         Inno Setup wizard images
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def square_crop(img: Image.Image) -> Image.Image:
    """A centred square holding the whole emblem.

    The emblem's ring is wider than the artwork is tall, so a plain square
    crop cut its sides off. Take a wider strip and pad above and below with
    the artwork's own background colour.
    """
    w, h = img.size
    side = min(w, int(h * 1.16))
    left = (w - side) // 2
    strip = img.crop((left, 0, left + side, h))
    canvas = Image.new("RGBA", (side, side), img.getpixel((left + 2, 2)))
    canvas.paste(strip, (0, (side - h) // 2))
    return canvas


def save_png(img: Image.Image, path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.resize((size, size), Image.LANCZOS).save(path, "PNG", optimize=True)


def main(source: Path) -> None:
    art = Image.open(source).convert("RGBA")
    square = square_crop(art)
    master = square.resize((1024, 1024), Image.LANCZOS)

    icons = ROOT / "frontend" / "src-tauri" / "icons"
    save_png(master, icons / "icon.png", 512)
    save_png(master, icons / "32x32.png", 32)
    save_png(master, icons / "128x128.png", 128)
    save_png(master, icons / "128x128@2x.png", 256)
    save_png(master, icons / "256x256.png", 256)
    master.save(icons / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    try:
        master.save(icons / "icon.icns")
    except Exception as exc:  # icns support depends on the Pillow build
        print(f"icon.icns not regenerated: {exc}")

    public = ROOT / "frontend" / "public"
    master.save(public / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    save_png(master, public / "apple-touch-icon.png", 180)
    save_png(master, public / "pwa-192x192.png", 192)
    save_png(master, public / "pwa-512x512.png", 512)

    save_png(master, ROOT / "frontend" / "src" / "assets" / "orion-logo.png", 256)
    save_png(master, public / "orion-logo.png", 256)

    assets = ROOT / "assets"
    save_png(master, assets / "Orion_Circular_Logo.png", 512)
    wide = art.copy()
    wide.thumbnail((1200, 1200), Image.LANCZOS)
    wide.save(assets / "Orion_Horizontal_Logo.png", "PNG", optimize=True)

    # Inno Setup wizard images (24-bit BMP works in every Inno version).
    installer = ROOT / "installer" / "windows"
    installer.mkdir(parents=True, exist_ok=True)
    bg = art.getpixel((5, 5))[:3]
    tall = Image.new("RGB", (328, 628), bg)  # 2x of Inno's 164x314 side panel
    emblem = master.resize((300, 300), Image.LANCZOS).convert("RGB")
    tall.paste(emblem, (14, 164))
    tall.save(installer / "wizard-large.bmp", "BMP")
    master.resize((110, 110), Image.LANCZOS).convert("RGB").save(installer / "wizard-small.bmp", "BMP")
    master.save(installer / "orion.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print("brand assets written")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: make_brand_assets.py <source.png>")
    main(Path(sys.argv[1]))
