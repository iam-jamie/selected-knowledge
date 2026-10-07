import json
import sys
from pathlib import Path

HEADER = "Draw a four-panel comic, no grid lines. The content of the four panels is below (one panel per line break). Do not draw panel numbers, labels, or any explanatory text in the image, only the content itself: "
LABELS = ["Top-left", "Top-right", "Bottom-left", "Bottom-right"]
GROUP_SIZE = len(LABELS)


def main():
    if len(sys.argv) < 2:
        print("用法: python extract_prompts.py <input.json>")
        sys.exit(1)

    src = Path(sys.argv[1])
    with src.open(encoding="utf-8") as f:
        scenes = json.load(f)

    prompts = [s.get("image_prompt") or "empty" for s in scenes]

    # 最後一組不足 4 筆，補 "empty"
    while len(prompts) % GROUP_SIZE != 0:
        prompts.append("empty")

    lines = []
    for i in range(0, len(prompts), GROUP_SIZE):
        group = prompts[i:i + GROUP_SIZE]
        body = "".join(f"{label}: {p} " for label, p in zip(LABELS, group)).strip()
        lines.append(HEADER + body)

    out = src.with_name(src.stem + "_four.txt")
    out.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()