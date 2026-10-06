import argparse
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

SRC_DIR = Path("images-pre")
DST_DIR = Path("images")
TARGET_SIZE = (1920, 1080)
EXTS = {".jpeg", ".jpg", ".png"}

DARK = 90        # 灰階低於此值視為黑邊
MAX_TRIM = 8     # 每邊最多往內削幾 px，避免吃到畫面裡的黑色物件
MARGIN = 4       # 削完後再多留的安全距離（吃掉抗鋸齒灰邊）


def find_panels(img, n):
    """用黑框連通區域找出 n*n 格的外框，找不到就回傳 None。"""
    w, h = img.size
    gray = np.array(img.convert("L"))
    labels, _ = ndimage.label(gray < DARK, structure=np.ones((3, 3)))

    cands = []
    for sl in ndimage.find_objects(labels):
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        cands.append(((x1 - x0) * (y1 - y0), (x0, y0, x1, y1)))
    cands.sort(reverse=True)

    top = cands[: n * n]
    if len(top) < n * n or top[-1][0] < 0.3 * w * h / (n * n):
        return None

    boxes = [b for _, b in top]
    boxes.sort(key=lambda b: (b[1] + b[3]) / 2)          # 先依 y 排
    ordered = []
    for r in range(n):                                    # 每列內再依 x 排
        ordered += sorted(boxes[r * n:(r + 1) * n], key=lambda b: b[0])
    return ordered


def inner_box(img, box):
    """從外框往內削掉黑線，再留一點安全邊。"""
    g = np.array(img.convert("L"))
    x0, y0, x1, y1 = box
    for _ in range(MAX_TRIM):
        if (g[y0, x0:x1] < DARK).mean() > 0.5:
            y0 += 1
        elif (g[y1 - 1, x0:x1] < DARK).mean() > 0.5:
            y1 -= 1
        elif (g[y0:y1, x0] < DARK).mean() > 0.5:
            x0 += 1
        elif (g[y0:y1, x1 - 1] < DARK).mean() > 0.5:
            x1 -= 1
        else:
            break
    return x0 + MARGIN, y0 + MARGIN, x1 - MARGIN, y1 - MARGIN


def crop_16_9(tile):
    """置中裁成 16:9，避免縮放變形。"""
    w, h = tile.size
    target = 16 / 9
    if w / h > target:
        nw = int(h * target)
        left = (w - nw) // 2
        return tile.crop((left, 0, left + nw, h))
    nh = int(w / target)
    top = (h - nh) // 2
    return tile.crop((0, top, w, top + nh))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("grid", type=int, nargs="?", default=3,
                        help="每邊切幾格，2 = 2x2，3 = 3x3（預設 3）")
    args = parser.parse_args()
    n = args.grid

    DST_DIR.mkdir(exist_ok=True)

    sources = sorted(p for p in SRC_DIR.iterdir() if p.suffix.lower() in EXTS)
    if not sources:
        print(f"{SRC_DIR} 裡找不到 .jpeg / .jpg / .png 檔案")
        return

    out_index = 1
    for src in sources:
        img = Image.open(src).convert("RGB")
        w, h = img.size

        panels = find_panels(img, n)
        if panels is None:
            print(f"{src.name}: 偵測不到完整邊框，改用等分切")
            panels = [
                (c * w // n, r * h // n, (c + 1) * w // n, (r + 1) * h // n)
                for r in range(n) for c in range(n)
            ]

        for box in panels:
            tile = img.crop(inner_box(img, box))
            tile = crop_16_9(tile).resize(TARGET_SIZE, Image.LANCZOS)
            tile.save(DST_DIR / f"{out_index:04d}.jpeg", "JPEG", quality=95)
            out_index += 1

        print(f"{src.name} -> 完成")

    print(f"共輸出 {out_index - 1} 張到 {DST_DIR}/")


if __name__ == "__main__":
    main()