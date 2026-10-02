#!/usr/bin/env python3
"""
split_prompts.py

從 storyboard.json 讀取每個分鏡的 image_prompt，
輸出成 ViralDNA 可直接貼上的 prompts.txt（每行一個 prompt，無空行、無編號）。

storyboard.json 格式範例：
[
  {
    "scene_id": 1,
    "start": 0.0,
    "end": 4.2,
    "duration": 4.2,
    "image_prompt": "A quiet forest path at dawn...",
    "sfx_keyword": null
  },
  ...
]

用法：
    python split_prompts.py storyboard.json prompts.txt
"""

import json
import sys
from pathlib import Path


def load_storyboard(json_path: str) -> list[dict]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise ValueError("storyboard.json 必須是一個非空的分鏡陣列")
    return data


def validate_scenes(scenes: list[dict]) -> None:
    """檢查每個分鏡是否有必要欄位，並依 scene_id 排序，確保順序正確。"""
    required = {"scene_id", "start", "end", "duration", "image_prompt"}
    for i, scene in enumerate(scenes):
        missing = required - scene.keys()
        if missing:
            raise ValueError(f"第 {i} 筆分鏡缺少欄位：{missing}")
        if not str(scene["image_prompt"]).strip():
            raise ValueError(f"scene_id={scene['scene_id']} 的 image_prompt 是空的")


def write_prompts(scenes: list[dict], output_path: str) -> None:
    scenes_sorted = sorted(scenes, key=lambda s: s["scene_id"])
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        for scene in scenes_sorted:
            # 把 prompt 內部若有換行/多餘空白都攤平成單行，
            # 避免 ViralDNA 誤判成多個分鏡。
            prompt = " ".join(str(scene["image_prompt"]).split())
            f.write(prompt + "\n")


def main():
    if len(sys.argv) != 3:
        print("用法：python split_prompts.py <storyboard.json> <prompts.txt>")
        sys.exit(1)

    storyboard_path, output_path = sys.argv[1], sys.argv[2]

    if not Path(storyboard_path).exists():
        print(f"找不到檔案：{storyboard_path}")
        sys.exit(1)

    scenes = load_storyboard(storyboard_path)
    validate_scenes(scenes)
    write_prompts(scenes, output_path)

    print(f"完成！共 {len(scenes)} 個分鏡的 prompt 已寫入 {output_path}")
    print("請確認貼進 ViralDNA 前，檔案末端沒有多餘空行。")


if __name__ == "__main__":
    main()
