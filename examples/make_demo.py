"""Create a deterministic, hand-authored cel-style raster evaluation input."""

from pathlib import Path

from PIL import Image, ImageDraw


SCALE = 3
SIZE = 256


def scaled(points):
    return [(int(x * SCALE), int(y * SCALE)) for x, y in points]


def main() -> None:
    image = Image.new("RGB", (SIZE * SCALE, SIZE * SCALE), "#d8edf1")
    draw = ImageDraw.Draw(image)
    draw.ellipse((18 * SCALE, 20 * SCALE, 238 * SCALE, 240 * SCALE), fill="#8dcbd0")
    draw.polygon(scaled([(30, 256), (43, 181), (85, 158), (169, 158), (215, 187), (230, 256)]), fill="#294363")
    draw.polygon(scaled([(85, 160), (103, 143), (155, 143), (174, 164), (156, 209), (103, 207)]), fill="#f1ba91")
    draw.ellipse((62 * SCALE, 40 * SCALE, 196 * SCALE, 186 * SCALE), fill="#f4c49d")
    draw.polygon(scaled([(62, 89), (55, 144), (78, 176), (86, 127), (104, 94)]), fill="#482d4f")
    draw.polygon(scaled([(62, 91), (66, 53), (102, 26), (165, 30), (201, 72), (193, 134), (177, 104), (166, 67), (138, 92), (103, 75)]), fill="#56355d")
    draw.polygon(scaled([(84, 48), (119, 29), (164, 35), (180, 57), (140, 46), (111, 63)]), fill="#735078")
    draw.polygon(scaled([(169, 54), (196, 75), (190, 145), (178, 166), (181, 112)]), fill="#3a2747")
    draw.polygon(scaled([(76, 122), (102, 111), (119, 122), (101, 129)]), fill="#ffffff")
    draw.polygon(scaled([(139, 122), (157, 111), (180, 120), (158, 130)]), fill="#ffffff")
    draw.ellipse((98 * SCALE, 114 * SCALE, 109 * SCALE, 128 * SCALE), fill="#31566d")
    draw.ellipse((151 * SCALE, 114 * SCALE, 162 * SCALE, 129 * SCALE), fill="#31566d")
    draw.ellipse((102 * SCALE, 119 * SCALE, 106 * SCALE, 126 * SCALE), fill="#172a39")
    draw.ellipse((155 * SCALE, 119 * SCALE, 159 * SCALE, 126 * SCALE), fill="#172a39")
    draw.line(scaled([(128, 127), (124, 143), (131, 145)]), fill="#c98372", width=2 * SCALE)
    draw.arc((111 * SCALE, 137 * SCALE, 151 * SCALE, 163 * SCALE), 18, 160, fill="#a64e5b", width=2 * SCALE)
    draw.polygon(scaled([(65, 187), (104, 207), (128, 238), (84, 226)]), fill="#355d83")
    draw.polygon(scaled([(174, 187), (156, 208), (130, 238), (183, 223)]), fill="#355d83")
    draw.polygon(scaled([(117, 209), (139, 209), (146, 256), (111, 256)]), fill="#d46065")
    image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    output = Path(__file__).with_name("demo_input.png")
    image.save(output)
    print(output)


if __name__ == "__main__":
    main()
