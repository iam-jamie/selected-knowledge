import argparse
from pathlib import Path

from PIL import Image

SRC_DIR = Path("images-pre")
DST_DIR = Path("images")
TARGET_SIZE = (1920, 1080)
EXTS = {".jpeg", ".jpg", ".png"}


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

        # 順序：由左到右、由上到下
        for row in range(n):
            for col in range(n):
                box = (
                    col * w // n,
                    row * h // n,
                    (col + 1) * w // n,
                    (row + 1) * h // n,
                )
                tile = img.crop(box).resize(TARGET_SIZE, Image.LANCZOS)
                tile.save(DST_DIR / f"{out_index:04d}.jpeg", "JPEG", quality=95)
                out_index += 1

        print(f"{src.name} -> 完成")

    print(f"共輸出 {out_index - 1} 張到 {DST_DIR}/")


if __name__ == "__main__":
    main()