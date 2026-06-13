"""
generate_icons.py
Run locally: python generate_icons.py

Requires: pip install pillow

Reads your existing logo from static/logo.png and generates a complete,
correctly-padded PWA icon set into static/icons/.

- "any" icons: logo fills the canvas (for browser tabs, desktop)
- "maskable" icons: logo centered in the inner 80% with navy background,
  so Android's circular/squircle crop doesn't cut off your logo
"""

from PIL import Image
import os

SRC_LOGO   = "static/logo.png"
OUT_DIR    = "static/icons"
BG_COLOR   = (15, 27, 45, 255)   # #0F1B2D — matches theme_color
SIZES      = [72, 96, 128, 144, 152, 192, 384, 512]

os.makedirs(OUT_DIR, exist_ok=True)

logo = Image.open(SRC_LOGO).convert("RGBA")

for size in SIZES:
    # ── "any" icon — logo fills canvas, transparent or white bg ──
    any_canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    logo_resized = logo.copy()
    logo_resized.thumbnail((size, size), Image.LANCZOS)
    x = (size - logo_resized.width) // 2
    y = (size - logo_resized.height) // 2
    any_canvas.paste(logo_resized, (x, y), logo_resized)
    any_canvas.save(f"{OUT_DIR}/icon-{size}x{size}.png")

    # ── "maskable" icon — logo in inner 80%, solid bg fills 100% ──
    mask_canvas = Image.new("RGBA", (size, size), BG_COLOR)
    inner_size = int(size * 0.8)  # 10% padding on each side
    logo_inner = logo.copy()
    logo_inner.thumbnail((inner_size, inner_size), Image.LANCZOS)
    x = (size - logo_inner.width) // 2
    y = (size - logo_inner.height) // 2
    mask_canvas.paste(logo_inner, (x, y), logo_inner)
    mask_canvas.save(f"{OUT_DIR}/icon-maskable-{size}x{size}.png")

# ── Apple touch icon — 180x180, NO transparency (iOS adds black bg to transparent PNGs) ──
apple_canvas = Image.new("RGB", (180, 180), BG_COLOR[:3])
apple_logo = logo.copy()
apple_logo.thumbnail((160, 160), Image.LANCZOS)
x = (180 - apple_logo.width) // 2
y = (180 - apple_logo.height) // 2
apple_canvas.paste(apple_logo, (x, y), apple_logo if apple_logo.mode == "RGBA" else None)
apple_canvas.save(f"{OUT_DIR}/apple-touch-icon.png")

print(f"✅ Generated {len(SIZES)*2 + 1} icons in {OUT_DIR}/")
print("Next: update manifest.json and base.html as shown below.")