# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Draw the launcher icons (stepscribe/data/stepscribe.ico and .png) with Pillow.

    python scripts/make_icons.py

The shapes follow the favicon in stepscribe/ui/server.py: a blue rounded square with a white "P".
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

DATA = Path(__file__).resolve().parents[1] / "stepscribe" / "data"
BLUE, WHITE = (31, 111, 235, 255), (255, 255, 255, 255)


def draw(size: int = 256) -> Image.Image:
    s = size / 32.0  # the favicon is drawn on a 32 x 32 grid
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(6 * s), fill=BLUE)
    w = max(2, int(3 * s))
    x0, y0, y1, x1 = 9 * s, 10 * s, 22 * s, 17 * s
    d.line([(x0, y1), (x0, y0), (x1, y0)], fill=WHITE, width=w, joint="curve")
    d.arc([x1 - 4 * s, y0, x1 + 4 * s, y0 + 8 * s], start=270, end=90, fill=WHITE, width=w)
    d.line([(x1, y0 + 8 * s), (13 * s, y0 + 8 * s)], fill=WHITE, width=w)
    return img


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    big = draw(256)
    big.save(DATA / "stepscribe.png")
    big.save(
        DATA / "stepscribe.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
