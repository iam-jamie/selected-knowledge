#!/usr/bin/env python3
"""
fetch_sfx.py

讀取 storyboard.json 裡每個分鏡的 sfx_keyword，分兩種來源處理：
  - 內容音效（預設，畫面配對用）：呼叫 Freesound API 搜尋並自動下載排名第一的
    候選音效（CC0 授權）
  - 敘事節奏音效（storyboard.json 裡該分鏡標示 "sfx_type": "rhythm"）：
    不打 API，直接去本地的 sound_effect/ 資料夾找同名檔案
    （例如 sfx_keyword="pop bright" → 找 sound_effect/pop bright.mp3）
兩種來源最後合併寫進同一份 sfx_map.json，可以直接接 build_video.py --sfx-map。

用法：
    export FREESOUND_API_KEY="你的API金鑰"
    python fetch_sfx.py --storyboard storyboard.json --output-dir sfx --rhythm-dir sound_effect

輸出：
    sfx/
        0004_123456.mp3       ← scene_id=0004，內容音效（Freesound sound id=123456）
        ...
    sfx_map.json              ← 自動產生，內容音效+節奏音效都在裡面
    fetch_report.json         ← 每個分鏡實際抓到的音效資訊，方便日後追查來源
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

FREESOUND_SEARCH_URL = "https://freesound.org/apiv2/search/text/"


def load_storyboard(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    return sorted(scenes, key=lambda s: s["scene_id"])


def build_license_filter(max_duration: float) -> str:
    # 只接受 CC0（公共領域）授權，並限制長度，避免搜到動輒好幾分鐘的環境音／混音檔
    return f'license:"Creative Commons 0" duration:[0.1 TO {max_duration}]'


def search_top_result(
    keyword: str, api_key: str, max_duration: float
) -> tuple[dict | None, str]:
    """
    搜尋並回傳排名第一的結果。
    如果完整關鍵字搜不到，自動退回只用前兩個字重試一次。
    回傳 (結果或None, 實際使用的關鍵字)。
    """
    def _search(q: str) -> list[dict]:
        params = {
            "query": q,
            "token": api_key,
            "filter": build_license_filter(max_duration),
            "fields": "id,name,license,duration,previews,url",
            "sort": "rating_desc",
            "page_size": 1,
        }
        resp = requests.get(FREESOUND_SEARCH_URL, params=params, timeout=15)
        if resp.status_code == 401:
            raise RuntimeError("API 金鑰無效或過期，請確認 FREESOUND_API_KEY 是否正確")
        resp.raise_for_status()
        return resp.json().get("results", [])

    results = _search(keyword)
    if results:
        return results[0], keyword

    words = keyword.split()
    if len(words) > 2:
        simplified = " ".join(words[:2])
        print(f"  完整關鍵字沒結果，改用簡化關鍵字重試：\"{simplified}\"")
        results = _search(simplified)
        if results:
            return results[0], simplified

    return None, keyword


def download_preview(url: str, dest_path: Path) -> None:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    dest_path.write_bytes(resp.content)


def find_rhythm_sfx(rhythm_dir: Path, keyword: str) -> Path | None:
    """在本地敘事節奏音效庫裡找同名檔案，例如 'pop bright' → pop bright.mp3。"""
    for ext in (".mp3", ".wav", ".m4a"):
        candidate = rhythm_dir / f"{keyword}{ext}"
        if candidate.exists():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description="從 Freesound 自動抓取分鏡對應的音效並產生 sfx_map.json")
    parser.add_argument("--storyboard", required=True, help="storyboard.json 路徑")
    parser.add_argument("--output-dir", default="sfx", help="音效檔輸出資料夾")
    parser.add_argument(
        "--sfx-map-output", default="sfx_map.json", help="自動產生的 sfx_map.json 輸出路徑"
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FREESOUND_API_KEY"),
        help="Freesound API key（預設讀取環境變數 FREESOUND_API_KEY）",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=20.0,
        help="搜尋時排除超過這個秒數的音效檔（預設20秒），避免抓到過長的環境音／混音檔",
    )
    parser.add_argument(
        "--rhythm-dir",
        default="../../assets/sound_effect",
        help="敘事節奏音效的本地資料夾（sfx_type=rhythm 的分鏡會來這裡找同名檔案）。"
             "預設假設在 episodes/<集數>/ 底下執行，往上兩層是專案根目錄的 assets/sound_effect/",
    )
    args = parser.parse_args()

    if not args.api_key:
        sys.exit(
            "找不到 API key。請用 --api-key 帶入，或先設定環境變數：\n"
            "  export FREESOUND_API_KEY=\"你的金鑰\""
        )

    storyboard_path = Path(args.storyboard)
    if not storyboard_path.exists():
        sys.exit(f"找不到 storyboard 檔案：{storyboard_path}")

    scenes = load_storyboard(str(storyboard_path))
    scenes_with_sfx = [s for s in scenes if s.get("sfx_keyword")]

    if not scenes_with_sfx:
        print("storyboard.json 裡沒有任何分鏡設定 sfx_keyword，沒有東西要抓。")
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rhythm_dir = Path(args.rhythm_dir)

    sfx_map: dict[str, str] = {}
    report = []
    not_found = []

    for scene in scenes_with_sfx:
        scene_id = scene["scene_id"]
        keyword = scene["sfx_keyword"]

        # ---- 敘事節奏音效：不打 API，直接從本地資料夾拿 ----
        if scene.get("sfx_type") == "rhythm":
            print(f"[scene {scene_id:04d}] 節奏音效：\"{keyword}\"", end=" ")
            local_path = find_rhythm_sfx(rhythm_dir, keyword)
            if local_path is None:
                print(f"→ 在 {rhythm_dir}/ 找不到 \"{keyword}.mp3\"")
                report.append({
                    "scene_id": scene_id, "keyword": keyword, "sfx_type": "rhythm", "found": False,
                })
                not_found.append(scene_id)
                continue
            print(f"→ 使用 {local_path}")
            sfx_map[str(scene_id)] = str(local_path)
            report.append({
                "scene_id": scene_id, "keyword": keyword, "sfx_type": "rhythm",
                "found": True, "file": str(local_path),
            })
            continue

        # ---- 內容音效：呼叫 Freesound API ----
        print(f"[scene {scene_id:04d}] 搜尋：\"{keyword}\"", end=" ")

        try:
            sound, used_keyword = search_top_result(keyword, args.api_key, args.max_duration)
        except Exception as e:
            print(f"→ 搜尋失敗：{e}")
            report.append({"scene_id": scene_id, "keyword": keyword, "found": False, "error": str(e)})
            not_found.append(scene_id)
            continue

        if sound is None:
            print(f"→ 沒找到符合條件的結果（{args.max_duration}秒內、CC0授權）")
            report.append({"scene_id": scene_id, "keyword": keyword, "found": False})
            not_found.append(scene_id)
            continue

        preview_url = sound.get("previews", {}).get("preview-hq-mp3")
        if not preview_url:
            print("→ 該結果沒有可下載的試聽檔，略過")
            report.append({"scene_id": scene_id, "keyword": keyword, "found": False})
            not_found.append(scene_id)
            continue

        filename = f"{scene_id:04d}_{sound['id']}.mp3"
        dest_path = output_dir / filename

        try:
            download_preview(preview_url, dest_path)
        except Exception as e:
            print(f"→ 下載失敗：{e}")
            report.append({"scene_id": scene_id, "keyword": keyword, "found": False, "error": str(e)})
            not_found.append(scene_id)
            continue

        print(f"→ {sound['name']}（{sound['duration']:.1f}s）")

        sfx_map[str(scene_id)] = str(dest_path)
        report.append({
            "scene_id": scene_id,
            "keyword": keyword,
            "used_keyword": used_keyword,
            "found": True,
            "file": str(dest_path),
            "sound_id": sound["id"],
            "name": sound["name"],
            "license": sound["license"],
            "duration": sound["duration"],
            "freesound_url": sound.get("url", ""),
        })

        time.sleep(0.3)  # 避免打太快觸發 rate limit

    sfx_map_path = Path(args.sfx_map_output)
    sfx_map_path.write_text(json.dumps(sfx_map, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = output_dir / "fetch_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成！{len(sfx_map)}/{len(scenes_with_sfx)} 個分鏡成功抓到音效並已寫入 {sfx_map_path}")
    print(f"音效檔存在：{output_dir}/")
    print(f"詳細來源紀錄：{report_path}")

    if not_found:
        ids = ", ".join(f"{i:04d}" for i in not_found)
        print(f"\n以下分鏡沒抓到音效（scene_id: {ids}），沒有寫進 sfx_map.json：")
        for s in scenes_with_sfx:
            if s["scene_id"] in not_found:
                print(f"  - scene_id={s['scene_id']:04d} keyword=\"{s['sfx_keyword']}\"")
        print("建議：把上面的關鍵字換成更通用的英文詞，或降低關鍵字的具體程度後重跑。")
        print("（重跑只會覆蓋 sfx_map.json 裡已有的內容，已抓到的分鏡不受影響）")

    print(f"\n可以直接接著跑：\n"
          f"  python ../../scripts/build_video.py --storyboard {args.storyboard} --images-dir images "
          f"--narration narration.mp3 --sfx-map {sfx_map_path}")


if __name__ == "__main__":
    main()
