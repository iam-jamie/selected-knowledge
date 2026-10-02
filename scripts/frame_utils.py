#!/usr/bin/env python3
"""
frame_utils.py

split_prompts.py 跟 build_video.py 共用的核心邏輯：
把 storyboard.json 的分鏡（scenes）攤平成一份「全域 frame 清單」。

背景：大多數分鏡只有一張圖（1 scene = 1 frame），但列舉句/快速反轉句
這種分鏡可能用 "frames" 欄位定義好幾張依序出現的圖（1 scene = N frames）。
不管哪種情況，兩支腳本都必須用**完全一致**的攤平順序跟編號方式，
不然 ViralDNA 產出的圖片編號會跟 build_video.py 讀取的編號對不上，
而且不會報錯，只會安靜地錯位——所以這段邏輯只寫一份，兩邊 import 同一份。

frame 的編號（frame_id）是全域連續編號，從1開始，不是每個分鏡重新算。
沒有 "frames" 欄位的分鏡，視為只有一個 frame（start_in_scene=0.0，
用該分鏡的 image_prompt），這樣舊格式的 storyboard.json 完全不用改，
frame_id 會跟 scene_id 一樣（1:1對應），行為跟改版前完全一致。
"""


def flatten_frames(scenes: list[dict]) -> list[dict]:
    """
    把所有分鏡攤平成全域 frame 清單，依照時間順序排列。
    每個 frame 是一個 dict，包含：
        frame_id     全域連續編號，從1開始（對應圖片檔名 0001.jpeg...）
        scene_id     這個 frame 屬於哪個分鏡（除錯/報告訊息用）
        image_prompt 這一格的 image prompt
        abs_start    這一格在全片的絕對開始時間（秒）
        abs_end      這一格的絕對結束時間 = 下一個frame的abs_start，
                     或（全片最後一個frame）該分鏡的 end
        duration     abs_end - abs_start
    """
    scenes_sorted = sorted(scenes, key=lambda s: s["scene_id"])

    raw_frames = []  # 先不算 abs_end，第二輪再補
    for scene in scenes_sorted:
        scene_frames = scene.get("frames")
        if scene_frames:
            for f in scene_frames:
                raw_frames.append({
                    "scene_id": scene["scene_id"],
                    "image_prompt": f["image_prompt"],
                    "abs_start": round(scene["start"] + f.get("start_in_scene", 0.0), 3),
                    "_scene_end": scene["end"],
                })
        else:
            if "image_prompt" not in scene:
                raise ValueError(
                    f"scene_id={scene['scene_id']} 既沒有 'frames' 也沒有 'image_prompt'，資料不完整"
                )
            raw_frames.append({
                "scene_id": scene["scene_id"],
                "image_prompt": scene["image_prompt"],
                "abs_start": round(scene["start"], 3),
                "_scene_end": scene["end"],
            })

    raw_frames.sort(key=lambda f: f["abs_start"])

    frames = []
    for i, f in enumerate(raw_frames, start=1):
        if i < len(raw_frames):
            abs_end = raw_frames[i]["abs_start"]  # 下一個frame的開始時間
        else:
            abs_end = f["_scene_end"]  # 全片最後一個frame，撐到所屬分鏡結束

        duration = round(abs_end - f["abs_start"], 3)
        frames.append({
            "frame_id": i,
            "scene_id": f["scene_id"],
            "image_prompt": f["image_prompt"],
            "abs_start": f["abs_start"],
            "abs_end": abs_end,
            "duration": duration,
        })

    return frames


def validate_frames(frames: list[dict]) -> None:
    """檢查攤平結果是否合理：時間遞增、沒有零長度或負長度的frame。"""
    for i, f in enumerate(frames):
        if f["duration"] <= 0:
            raise ValueError(
                f"frame_id={f['frame_id']}（scene_id={f['scene_id']}）"
                f"的時長是 {f['duration']}秒，不合理（可能是 start_in_scene 設定超出分鏡時長，"
                f"或多個frame的start_in_scene重複/逆序）"
            )
        if i > 0 and f["abs_start"] < frames[i - 1]["abs_start"]:
            raise ValueError(
                f"frame_id={f['frame_id']} 的開始時間比前一個frame還早，攤平順序異常"
            )
