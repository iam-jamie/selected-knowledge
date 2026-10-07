#!/usr/bin/env python3
"""
build_video.py

讀取 storyboard.json（每個分鏡的時長）+ 依序命名的圖片資料夾（1.jpg, 2.jpg...）
+ 一整條旁白音檔，用 FFmpeg 合成成一支影片。
可選：讀取 sfx_map.json（scene_id -> 音效檔路徑）把音效疊到對應時間點。

storyboard.json 格式同 split_prompts.py，另外可選欄位 sfx_offset：
音效要在分鏡「開始後幾秒」才響起（預設0＝分鏡一開始就響）。
例如疑問句/重點的「叮」音效通常要在句子講完那一刻才響，
就把 sfx_offset 設成接近該分鏡的 duration。

sfx_map.json 格式範例（可選）：
{
  "2": "sfx/bushes_rustling.mp3",
  "5": "sfx/heartbeat.mp3"
}

Zoom（拉 retention 用）：
  - 預設開啟，只對「開始時間 < --zoom-until 秒」的分鏡做 zoom（預設 60 秒）。
  - 每個 zoom 分鏡：前 --zoom-seconds 秒緩動（餘弦緩動），之後靜止；
    放大（1.0 → max）和縮小（max → 1.0）交替。
  - 超過 --zoom-until 的分鏡走原本的快速路徑（concat demuxer 一次編碼）。
  - --no-zoom 完全關閉 zoom，行為和舊版一樣。

音量：
  - 旁白預設用兩遍式 loudnorm 標準化到 --target-lufs（預設 -16 LUFS），
    linear 模式不壓縮動態；--no-loudnorm 可關閉。
  - 音效先拉平再降到 --sfx-volume-db（預設 -18 dB），混音後加限幅器避免爆音。

用法：
    python build_video.py \
        --storyboard storyboard.json \
        --images-dir images \
        --narration narration.mp3 \
        [--sfx-map sfx_map.json] \
        [--width 1920] [--height 1080] [--fps 30] \
        [--no-zoom] [--zoom-until 60] [--max-zoom 1.05] [--zoom-seconds 1.0] \
        [--target-lufs -16] [--no-loudnorm] [--sfx-volume-db -18] \
        [--output-dir output] [--output 自訂完整檔名.mp4]

預設輸出到：{output-dir}/{narration 檔名去掉副檔名}_影片.mp4（output-dir 預設是 output/）
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def load_storyboard(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    return sorted(scenes, key=lambda s: s["scene_id"])


def try_find_image_for_scene(images_dir: Path, scene_id: int) -> Path | None:
    """
    依序找對應 scene_id 的圖片，找不到回傳 None（不拋錯，由呼叫端決定怎麼處理）。
    ViralDNA 批次下載的檔名是 4 位數升序、零補位，例如 0001.jpeg, 0002.jpeg...
    所以優先找零補位格式，找不到才退回無補位格式（相容舊的命名方式）。
    """
    candidates = []
    for ext in (".jpeg", ".jpg", ".png", ".webp"):
        candidates.append(images_dir / f"{scene_id:04d}{ext}")  # 0001.jpeg
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidates.append(images_dir / f"{scene_id}{ext}")  # 1.jpg（相容用）

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_scene_images(
    scenes: list[dict], images_dir: Path, strict: bool
) -> tuple[dict[int, Path], list[dict]]:
    """
    幫每個分鏡找出實際要用的圖片路徑。
    - 先找出所有分鏡各自的圖片有沒有存在，一次列出全部缺圖，而不是找到第一個就中斷。
    - strict=True：只要有缺圖就直接報錯（保留舊行為）。
    - strict=False（預設）：缺圖的分鏡用「前一個存在的分鏡的圖」頂替
      （維持時長對齊；如果連最前面幾個分鏡都缺圖，找不到「前一張」，
      就往後找最近的一張頂替）。
    回傳：{scene_id: 實際使用的圖片路徑}, 缺圖分鏡清單（原始 scene 資料）
    """
    found: dict[int, Path] = {}
    missing_scenes: list[dict] = []

    for scene in scenes:
        img_path = try_find_image_for_scene(images_dir, scene["scene_id"])
        if img_path is not None:
            found[scene["scene_id"]] = img_path
        else:
            missing_scenes.append(scene)

    if missing_scenes and strict:
        ids = ", ".join(str(s["scene_id"]) for s in missing_scenes)
        raise FileNotFoundError(f"以下 scene_id 缺少對應圖片：{ids}")

    if not missing_scenes:
        return found, missing_scenes

    # 補位：往前找最近一張已存在的圖，找不到就往後找
    resolved: dict[int, Path] = {}
    sorted_ids = [s["scene_id"] for s in scenes]
    for scene_id in sorted_ids:
        if scene_id in found:
            resolved[scene_id] = found[scene_id]
            continue
        fallback = None
        for candidate_id in reversed([i for i in sorted_ids if i < scene_id]):
            if candidate_id in found:
                fallback = found[candidate_id]
                break
        if fallback is None:
            for candidate_id in [i for i in sorted_ids if i > scene_id]:
                if candidate_id in found:
                    fallback = found[candidate_id]
                    break
        if fallback is None:
            raise FileNotFoundError(
                "images-dir 裡完全沒有任何一張可用的圖片，無法補位。"
            )
        resolved[scene_id] = fallback

    return resolved, missing_scenes


def print_missing_report(missing_scenes: list[dict]) -> None:
    if not missing_scenes:
        return
    print("\n" + "=" * 60)
    print(f"警告：以下 {len(missing_scenes)} 個分鏡缺少圖片，已用鄰近分鏡的圖片頂替時長：")
    for s in missing_scenes:
        print(f"  - scene_id={s['scene_id']:04d}（{s['duration']}s）")
        print(f"    prompt: {s['image_prompt']}")
    print("建議：把上面的 prompt 拿去 ViralDNA 補產對應編號的圖片後，重新命名成")
    print("      0000 補位格式（例如 scene_id=59 → 0059.jpeg）放回圖片資料夾重跑。")
    print("=" * 60 + "\n")


def _concat_quote(path: Path) -> str:
    """concat demuxer 的路徑：絕對路徑 + 單引號，路徑內的單引號要跳脫。"""
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def build_concat_file(
    scenes: list[dict],
    resolved_images: dict[int, Path],
    tmp_dir: Path,
    name: str = "concat_list.txt",
) -> Path:
    """
    產生 FFmpeg concat demuxer 用的清單檔。
    注意 FFmpeg 的已知行為：最後一個 duration 會被忽略，
    因此需要把最後一張圖片再重複列一次（不加 duration）。
    """
    concat_path = tmp_dir / name
    lines = []
    last_image_path = None

    for scene in scenes:
        img_path = resolved_images[scene["scene_id"]]
        last_image_path = img_path
        lines.append(_concat_quote(img_path))
        lines.append(f"duration {scene['duration']}")

    # 修正最後一筆 duration 被忽略的問題
    if last_image_path is not None:
        lines.append(_concat_quote(last_image_path))

    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat_path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    print("執行：", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"指令失敗：{' '.join(cmd)}")
    return result


def build_fast_video(
    concat_path: Path, width: int, height: int, fps: int, out_path: Path
) -> Path:
    """原本的快速路徑：concat demuxer 一次編碼，不做 zoom。"""
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        str(out_path),
    ]
    run(cmd)
    return out_path


def build_zoom_segment(
    image_path: Path,
    frame_count: int,
    zoom_in: bool,
    width: int,
    height: int,
    fps: int,
    max_zoom: float,
    zoom_seconds: float,
    out_path: Path,
) -> Path:
    """
    單一分鏡的 zoom 片段。
    前 zoom_seconds 秒用餘弦緩動從 1.0 → max_zoom（或反向），之後停在終點。
    先放大到輸出尺寸 2 倍再 zoompan，最後縮回輸出尺寸，避免畫面抖動。
    """
    motion_w, motion_h = width * 2, height * 2
    zoom_frames = max(min(frame_count, round(zoom_seconds * fps)), 2)
    span = max(zoom_frames - 1, 1)
    eased = f"(1-cos(PI*min(on\\,{span})/{span}))/2"
    amount = max_zoom - 1
    if zoom_in:
        zoom_expr = f"1+{amount:.4f}*{eased}"
    else:
        zoom_expr = f"{max_zoom:.4f}-{amount:.4f}*{eased}"

    vf = (
        f"scale={motion_w}:{motion_h}:force_original_aspect_ratio=increase,"
        f"crop={motion_w}:{motion_h},"
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frame_count}:s={motion_w}x{motion_h}:fps={fps},"
        f"scale={width}:{height},format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(image_path),
        "-vf", vf,
        "-frames:v", str(frame_count),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-an",
        str(out_path),
    ]
    run(cmd)
    return out_path


def build_silent_video(
    scenes: list[dict],
    resolved_images: dict[int, Path],
    width: int,
    height: int,
    fps: int,
    tmp_dir: Path,
    zoom: bool,
    zoom_until: float,
    max_zoom: float,
    zoom_seconds: float,
) -> Path:
    """
    zoom 關閉：全部分鏡走快速路徑（和舊版一樣）。
    zoom 開啟：開始時間 < zoom_until 的分鏡各自做 zoom 片段，
    其餘分鏡走快速路徑，最後用 -c copy 接起來。
    整個分鏡要嘛全 zoom、要嘛全不 zoom，不會在分鏡中間切換。
    """
    silent_video_path = tmp_dir / "silent_video.mp4"

    zoom_scenes: list[dict] = []
    if zoom:
        for scene in scenes:
            if scene["start"] < zoom_until:
                zoom_scenes.append(scene)
            else:
                break
    rest_scenes = scenes[len(zoom_scenes):]

    if not zoom_scenes:
        concat_path = build_concat_file(scenes, resolved_images, tmp_dir)
        return build_fast_video(concat_path, width, height, fps, silent_video_path)

    print(f"Zoom：前 {len(zoom_scenes)} 個分鏡（開始時間 < {zoom_until:g} 秒）；"
          f"其餘 {len(rest_scenes)} 個分鏡走快速路徑")

    segments_dir = tmp_dir / "zoom_segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []

    # 用累積時間換算每段幀數，避免每段各自四捨五入造成的時間漂移
    elapsed = 0.0
    for i, scene in enumerate(zoom_scenes):
        start_frame = round(elapsed * fps)
        elapsed += float(scene["duration"])
        frame_count = max(round(elapsed * fps) - start_frame, 1)
        seg_path = segments_dir / f"segment_{i:05d}.mp4"
        print(f"Zoom 分鏡 {i + 1}/{len(zoom_scenes)}（scene_id={scene['scene_id']}）")
        build_zoom_segment(
            resolved_images[scene["scene_id"]],
            frame_count,
            zoom_in=(i % 2 == 0),
            width=width,
            height=height,
            fps=fps,
            max_zoom=max_zoom,
            zoom_seconds=zoom_seconds,
            out_path=seg_path,
        )
        parts.append(seg_path)

    if rest_scenes:
        rest_concat = build_concat_file(
            rest_scenes, resolved_images, tmp_dir, name="concat_rest.txt"
        )
        rest_video = build_fast_video(
            rest_concat, width, height, fps, tmp_dir / "rest_video.mp4"
        )
        parts.append(rest_video)

    join_list = tmp_dir / "concat_parts.txt"
    join_list.write_text(
        "".join(_concat_quote(p) + "\n" for p in parts), encoding="utf-8"
    )
    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(join_list),
        "-c", "copy",
        str(silent_video_path),
    ])
    return silent_video_path


def measure_loudnorm(
    path: Path, target_lufs: float, true_peak: float
) -> str | None:
    """
    loudnorm 第一遍：量旁白目前的響度，回傳第二遍要用的 filter 字串。
    量不到（例如輸出格式異常）就回傳 None，由呼叫端退回單遍式。
    """
    result = run([
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:print_format=json",
        "-f", "null", "-",
    ])
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr, re.S)
    if not match:
        return None
    try:
        stats = json.loads(match.group(0))
        print(
            f"旁白原始響度：{stats['input_i']} LUFS，"
            f"true peak {stats['input_tp']} dBTP"
        )
        return (
            f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:"
            f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
            f"measured_LRA={stats['input_lra']}:"
            f"measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:linear=true"
        )
    except (KeyError, ValueError):
        return None


def build_audio_track(
    scenes: list[dict],
    narration_path: Path,
    sfx_map: dict[str, str],
    tmp_dir: Path,
    max_sfx_seconds: float,
    sfx_volume_db: float,
    sfx_fade_seconds: float,
    target_lufs: float | None = -16.0,
    true_peak: float = -1.5,
) -> Path:
    """
    旁白當主音軌：
      0. target_lufs 不是 None 時，先用兩遍式 loudnorm 把旁白標準化到目標響度
         （linear 模式，不壓縮動態）。
    若有 sfx_map，把每個音效：
      1. atrim 截斷到「分鏡時長」跟「max_sfx_seconds 上限」兩者取較短的那個
         （修正過去音效檔過長、蓋掉整段影片的問題）
      2. dynaudnorm 先拉平每個音效檔本身忽大忽小的音量（不同音效檔來源錄音音量差很多）
      3. volume 再統一往下壓到比旁白小聲（預設 -18dB）
      4. afade 在截斷點前做短暫淡出，避免生硬喀一聲切斷
      5. adelay 對齊到分鏡開始的時間點
    最後跟旁白 amix，再過一個限幅器（約 -1 dBFS）避免混音後爆音。
    """
    audio_out_path = tmp_dir / "final_audio.m4a"

    narr_filter = "anull"
    if target_lufs is not None:
        narr_filter = measure_loudnorm(narration_path, target_lufs, true_peak) or (
            f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11"
        )
    limiter = "alimiter=limit=0.89:level=disabled"

    scene_by_id = {str(s["scene_id"]): s for s in scenes}

    inputs = ["-i", str(narration_path)]
    filter_parts = [f"[0:a]{narr_filter}[narr]"]
    mix_labels = ["[narr]"]

    idx = 1
    for scene_id, sfx_path in sfx_map.items():
        scene = scene_by_id.get(str(scene_id))
        if scene is None:
            print(f"警告：sfx_map 裡的 scene_id={scene_id} 不存在於 storyboard，略過")
            continue
        if not Path(sfx_path).exists():
            print(f"警告：找不到音效檔 {sfx_path}，略過")
            continue

        inputs += ["-i", str(sfx_path)]

        # sfx_offset：音效要在分鏡開始後幾秒才響（預設0＝分鏡一開始就響）
        # 疑問句/重點的音效通常會設成接近 duration，讓它落在句尾
        offset = float(scene.get("sfx_offset", 0.0) or 0.0)
        offset = max(0.0, min(offset, scene["duration"]))
        delay_ms = int(round((scene["start"] + offset) * 1000))
        label = f"[a{idx}]"

        # 截斷長度：分鏡「剩餘時長」（扣掉offset）跟上限秒數取較短的那個，
        # 避免音效播到下一個分鏡去
        remaining = max(scene["duration"] - offset, 0.05)
        cap_seconds = min(remaining, max_sfx_seconds)
        # 淡出長度不能超過截斷長度本身
        fade_dur = min(sfx_fade_seconds, max(cap_seconds - 0.05, 0.05))
        fade_start = max(cap_seconds - fade_dur, 0.0)

        filter_parts.append(
            f"[{idx}:a]atrim=0:{cap_seconds:.3f},asetpts=PTS-STARTPTS,"
            f"dynaudnorm=f=150:g=15,volume={sfx_volume_db}dB,"
            f"afade=t=out:st={fade_start:.3f}:d={fade_dur:.3f},"
            f"adelay={delay_ms}|{delay_ms}{label}"
        )
        mix_labels.append(label)
        idx += 1

    if idx == 1:
        # 沒有可用的音效，只輸出標準化後的旁白
        filter_complex = ";".join(filter_parts + [f"[narr]{limiter}[aout]"])
    else:
        mix_filter = (
            "".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0,{limiter}[aout]"
        )
        filter_complex = ";".join(filter_parts + [mix_filter])

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-c:a", "aac", "-b:a", "192k",
        str(audio_out_path),
    ]
    run(cmd)
    return audio_out_path


def mux_video_audio(silent_video: Path, audio_path: Path, output_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(silent_video),
        "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]
    run(cmd)


def main():
    parser = argparse.ArgumentParser(description="把分鏡圖片 + 旁白（+音效）合成影片")
    parser.add_argument("--storyboard", required=True, help="storyboard.json 路徑")
    parser.add_argument("--images-dir", required=True, help="圖片資料夾（1.jpg, 2.jpg...)")
    parser.add_argument("--narration", required=True, help="完整旁白音檔路徑")
    parser.add_argument("--sfx-map", default=None, help="可選：scene_id -> 音效檔路徑 的 json")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--output-dir",
        default="output",
        help="輸出資料夾，預設 output/（相對於執行時的所在目錄，通常是 episode 資料夾底下）",
    )
    parser.add_argument("--output", default=None, help="自訂完整輸出檔名（含路徑），預設為 {output-dir}/{旁白檔名}_影片.mp4")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="缺圖時直接報錯中斷（預設行為改成：缺圖用鄰近分鏡的圖片頂替並印出報告，不中斷）",
    )
    parser.add_argument(
        "--zoom",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="圖片 zoom 效果總開關，預設開啟；用 --no-zoom 完全關閉",
    )
    parser.add_argument(
        "--zoom-until",
        type=float,
        default=60.0,
        help="只對開始時間小於這個秒數的分鏡做 zoom，之後走快速路徑（預設60秒）",
    )
    parser.add_argument(
        "--max-zoom",
        type=float,
        default=1.05,
        help="最大縮放倍率（預設1.05，即放大5%%）",
    )
    parser.add_argument(
        "--zoom-seconds",
        type=float,
        default=1.0,
        help="每個分鏡 zoom 動作的持續秒數，之後畫面靜止（預設1.0秒）",
    )
    parser.add_argument(
        "--max-sfx-seconds",
        type=float,
        default=4.0,
        help="單個音效最長播放秒數上限，超過分鏡時長或這個值都會被截斷（預設4秒）",
    )
    parser.add_argument(
        "--sfx-volume-db",
        type=float,
        default=-18.0,
        help="音效相對於旁白的音量調整（單位dB，負值變小聲，預設-18）",
    )
    parser.add_argument(
        "--sfx-fade-seconds",
        type=float,
        default=0.3,
        help="音效結尾淡出秒數，避免生硬截斷（預設0.3秒）",
    )
    parser.add_argument(
        "--target-lufs",
        type=float,
        default=-16.0,
        help="旁白目標響度（LUFS），預設 -16；YouTube 參考值約 -14，想更響可設 -14",
    )
    parser.add_argument(
        "--no-loudnorm",
        action="store_true",
        help="不調整旁白響度（沿用原音檔音量）",
    )
    args = parser.parse_args()

    if args.max_zoom < 1.0:
        sys.exit("--max-zoom 必須 >= 1.0")
    if args.zoom_seconds <= 0:
        sys.exit("--zoom-seconds 必須 > 0")

    storyboard_path = Path(args.storyboard)
    images_dir = Path(args.images_dir)
    narration_path = Path(args.narration)

    if not storyboard_path.exists():
        sys.exit(f"找不到 storyboard 檔案：{storyboard_path}")
    if not images_dir.exists():
        sys.exit(f"找不到圖片資料夾：{images_dir}")
    if not narration_path.exists():
        sys.exit(f"找不到旁白音檔：{narration_path}")

    sfx_map = {}
    if args.sfx_map:
        sfx_map_path = Path(args.sfx_map)
        if sfx_map_path.exists():
            sfx_map = json.loads(sfx_map_path.read_text(encoding="utf-8"))
        else:
            print(f"警告：找不到 sfx-map 檔案 {sfx_map_path}，將略過音效")

    scenes = load_storyboard(str(storyboard_path))

    output_path = (
        Path(args.output)
        if args.output
        else Path(args.output_dir) / f"{narration_path.stem}_影片.mp4"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        print(f"共 {len(scenes)} 個分鏡，檢查圖片是否齊全...")
        resolved_images, missing_scenes = resolve_scene_images(scenes, images_dir, args.strict)
        print_missing_report(missing_scenes)

        print("開始建立圖片序列...")
        silent_video = build_silent_video(
            scenes, resolved_images, args.width, args.height, args.fps, tmp_dir,
            zoom=args.zoom,
            zoom_until=args.zoom_until,
            max_zoom=args.max_zoom,
            zoom_seconds=args.zoom_seconds,
        )

        print("開始處理音軌...")
        audio_path = build_audio_track(
            scenes, narration_path, sfx_map, tmp_dir,
            max_sfx_seconds=args.max_sfx_seconds,
            sfx_volume_db=args.sfx_volume_db,
            sfx_fade_seconds=args.sfx_fade_seconds,
            target_lufs=None if args.no_loudnorm else args.target_lufs,
        )

        print("合成最終影片...")
        mux_video_audio(silent_video, audio_path, output_path)

    print(f"完成！輸出檔案：{output_path}")
    if missing_scenes:
        ids = ", ".join(f"{s['scene_id']:04d}" for s in missing_scenes)
        print(f"提醒：這支影片裡有 {len(missing_scenes)} 個分鏡是用頂替圖片產生的（scene_id: {ids}）。")
        print("補完正確的圖之後，重新執行同一條指令即可覆蓋輸出。")


if __name__ == "__main__":
    main()