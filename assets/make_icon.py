"""Generate the XRDLab app icon (a stylised diffraction pattern) as a .ico."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Rounded dark tile background.
d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=44, fill=(24, 27, 34, 255))

baseline = SIZE - 56
d.line([(28, baseline), (SIZE - 28, baseline)], fill=(90, 96, 110, 255), width=3)

# A few diffraction "peaks" of varying height/colour.
peaks = [
    (70, 150, (31, 119, 180, 255)),   # blue
    (110, 96, (255, 127, 14, 255)),   # orange (tallest region)
    (150, 60, (255, 127, 14, 255)),
    (150, 130, (31, 119, 180, 255)),
    (196, 110, (44, 160, 44, 255)),   # green
]
for cx, h, color in peaks:
    top = baseline - h
    d.polygon([(cx - 9, baseline), (cx, top), (cx + 9, baseline)], fill=color)
    d.line([(cx, baseline), (cx, top)], fill=color, width=4)

out = Path(__file__).with_name("xrdlab.ico")
img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out)
