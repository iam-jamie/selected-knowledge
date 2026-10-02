#!/usr/bin/env python3
"""
從 Wikimedia Commons 下載 Public Domain / CC0 圖片。

用法(在集數資料夾底下執行,比照 fetch_sfx.py 的風格):
    cd episodes/000_短標題
    python ../../scripts/fetch_commons_images.py "Robert Owen portrait,Sykes-Picot Agreement map" --output-dir archival_photos

每個關鍵字最多下載 3 張符合零風險授權(Public Domain 或 CC0)的圖片,
預設存到「目前資料夾」底下的 archival_photos/(每一集自己一份,不共用),
檔名格式: keyword_1.jpg, keyword_2.jpg ...
同時會產生 download_log.json 記錄每張圖的來源、標題、授權,方便人工審核。
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

API_URL = "https://commons.wikimedia.org/w/api.php"
# 依 Wikimedia API 使用規範,User-Agent 需要包含聯絡方式,請填上你的資訊
HEADERS = {
    "User-Agent": "CuriousCharlieArchivalFetcher/1.0 (contact: YOUR_EMAIL_HERE)"
}
IMAGES_PER_KEYWORD = 3
SEARCH_LIMIT = 30  # 每個關鍵字先抓多一點候選,再用授權篩選
THUMB_WIDTH = 1600  # 抓縮圖而非原始檔,避免觸發 Wikimedia 的批次下載限速
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 8  # 遇到 429 時的預設等待秒數(若回應有 Retry-After 則優先用那個)


def is_license_ok(license_short_name: str) -> bool:
    """零風險授權判斷: 收 Public Domain / CC0, 排除任何需要標出處的 CC-BY 系列。"""
    if not license_short_name:
        return False
    name = license_short_name.strip().lower()
    if "by" in name:  # CC-BY, CC-BY-SA 都含 "by", 一律排除
        return False
    return name.startswith("pd") or "public domain" in name or "cc0" in name


def search_commons(keyword: str, limit: int = SEARCH_LIMIT):
    """搜尋 Commons 上的檔案,回傳依搜尋相關度排序的候選清單。"""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f'filetype:bitmap "{keyword}"',
        "gsrnamespace": 6,  # File namespace
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiurlwidth": THUMB_WIDTH,  # 連帶要求縮圖網址(thumburl),下載時用這個而非原始檔
        "iiextmetadatafilter": "LicenseShortName",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})

    results = []
    for page in pages.values():
        imageinfo = page.get("imageinfo")
        if not imageinfo:
            continue
        info = imageinfo[0]
        license_name = (
            info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        )
        results.append(
            {
                "index": page.get("index", 9999),  # 原始搜尋排名
                "title": page.get("title", ""),
                "url": info.get("url", ""),  # 原始檔連結,只用來記錄來源,不下載這個
                "download_url": info.get("thumburl") or info.get("url", ""),
                "license": license_name,
            }
        )
    results.sort(key=lambda r: r["index"])
    return results


def sanitize_keyword(keyword: str) -> str:
    """把關鍵字轉成安全的檔名片段。"""
    keyword = keyword.strip()
    keyword = re.sub(r"[^\w\s-]", "", keyword)
    keyword = re.sub(r"\s+", "_", keyword)
    return keyword or "untitled"


def download_with_retry(url: str, dest_path: Path, max_retries: int = MAX_RETRIES) -> None:
    """下載檔案,遇到 429(限速)時依 Retry-After 或預設秒數等待後重試。"""
    for attempt in range(1, max_retries + 1):
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", RETRY_WAIT_SECONDS))
            if attempt == max_retries:
                resp.raise_for_status()  # 重試用完,直接拋出讓上層記錄失敗
            print(f"  [限速] 429,等待 {wait} 秒後重試({attempt}/{max_retries})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        dest_path.write_bytes(resp.content)
        return


def process_keyword(keyword: str, output_dir: Path):
    safe_name = sanitize_keyword(keyword)
    try:
        candidates = search_commons(keyword)
    except Exception as e:
        print(f"[錯誤] 搜尋 '{keyword}' 失敗: {e}")
        return []

    log_entries = []
    downloaded = 0
    for item in candidates:
        if downloaded >= IMAGES_PER_KEYWORD:
            break
        if not is_license_ok(item["license"]):
            continue

        ext = Path(urlparse(item["download_url"]).path).suffix or ".jpg"
        next_index = downloaded + 1
        filename = f"{safe_name}_{next_index}{ext}"
        dest_path = output_dir / filename

        try:
            download_with_retry(item["download_url"], dest_path)
        except Exception as e:
            print(f"[下載失敗] {keyword} - {item['title']}: {e}")
            continue
        finally:
            time.sleep(1)  # 每張圖之間留間隔,避免密集請求再次觸發限速

        downloaded += 1
        log_entries.append(
            {
                "keyword": keyword,
                "filename": filename,
                "commons_title": item["title"],
                "license": item["license"],
                "source_url": item["url"],
            }
        )
        print(f"[完成] {filename}  <-  {item['title']} ({item['license']})")

    if downloaded == 0:
        print(f"[提醒] '{keyword}' 沒有找到符合 Public Domain / CC0 的圖片")

    return log_entries


def main():
    parser = argparse.ArgumentParser(
        description="從 Wikimedia Commons 下載 Public Domain / CC0 授權的歷史照片"
    )
    parser.add_argument(
        "keywords", help='逗號分隔的關鍵字,例如 "Robert Owen portrait,Haymarket riot 1886"'
    )
    parser.add_argument(
        "--output-dir",
        default="archival_photos",
        help="輸出資料夾,預設為目前資料夾底下的 archival_photos/(每一集執行時各自獨立)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True, parents=True)
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    all_logs = []
    for keyword in keywords:
        all_logs.extend(process_keyword(keyword, output_dir))
        time.sleep(0.5)  # 對 API 保持禮貌,避免速率限制

    log_path = output_dir / "download_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(all_logs, f, ensure_ascii=False, indent=2)

    print(f"\n共下載 {len(all_logs)} 張圖片,記錄存於 {log_path}")


if __name__ == "__main__":
    main()