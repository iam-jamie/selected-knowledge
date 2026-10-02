#!/usr/bin/env python3
"""
json_to_srt.py

把 storyboard.json 轉回校正過的 .srt 字幕檔。
用的是每個分鏡底下的 cues（原始SRT逐句時間戳+校正後文字），
不是分鏡合併後的 text——避免字幕顯示時間過長、內容太擠。

用法：
    python json_to_srt.py storyboard.json corrected.srt
"""

import json
import sys
from pathlib import Path


def load_storyboard(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    return sorted(scenes, key=lambda s: s["scene_id"])


def flatten_cues(scenes: list[dict]) -> list[dict]:
    """
    把所有分鏡底下的 cues 攤平成一份依時間排序的逐句清單。
    如果分鏡沒有 cues 欄位（舊格式），退回用分鏡本身的 start/end/text 當一句。
    """
    all_cues = []
    for scene in scenes:
        cues = scene.get("cues")
        if cues:
            all_cues.extend(cues)
        else:
            all_cues.append({
                "start": scene["start"],
                "end": scene["end"],
                "text": scene["text"],
            })
    all_cues.sort(key=lambda c: c["start"])
    return all_cues


def format_srt_timecode(seconds: float) -> str:
    """把秒數轉成 SRT 格式：HH:MM:SS,mmm"""
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def write_srt(cues: list[dict], output_path: str) -> None:
    lines = []
    for i, cue in enumerate(cues, start=1):
        start_tc = format_srt_timecode(cue["start"])
        end_tc = format_srt_timecode(cue["end"])
        text = cue["text"].strip()
        lines.append(str(i))
        lines.append(f"{start_tc} --> {end_tc}")
        lines.append(text)
        lines.append("")  # SRT 區塊之間要空一行

    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def main():
    if len(sys.argv) != 3:
        print("用法：python json_to_srt.py <storyboard.json> <輸出.srt>")
        sys.exit(1)

    storyboard_path, output_path = sys.argv[1], sys.argv[2]

    if not Path(storyboard_path).exists():
        print(f"找不到檔案：{storyboard_path}")
        sys.exit(1)

    scenes = load_storyboard(storyboard_path)
    cues = flatten_cues(scenes)
    write_srt(cues, output_path)

    print(f"完成！共 {len(cues)} 句字幕已寫入 {output_path}（保留原始SRT逐句時間顆粒度）")


if __name__ == "__main__":
    main()
