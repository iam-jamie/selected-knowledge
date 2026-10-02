# Curious Charlie — YouTube 分鏡/影片自動化 Pipeline

這個專案把「SRT 逐字稿 → 分鏡設計 → AI 生圖 → 音效 → 成品影片」整條流程自動化，
只有「生圖」跟「分鏡文字設計」還需要人工/AI輔助介入，其餘都是腳本一鍵跑完。

**生圖預設使用 3×3 九宮格**（一張圖 = 9 個分鏡，省生圖次數）。2×2 四宮格仍保留，用法見各步驟的「改用四宮格」說明。

---

## 整體 Workflow

```
① 用 Buzz 從錄音檔產出 SRT 逐字稿（手動）
        ↓
② 把 SRT + 視覺風格指南(docs/) 貼給 Claude，請它照 docs/storyboard-prompt-guide.md
   的方法論產出 storyboard.json（分鏡主控檔）                              ← AI輔助
        ↓
③ scripts/extract_prompts_nine.py
   storyboard.json → storyboard_nine.txt（每 9 個 image_prompt 合併成一組九宮格漫畫 prompt）
        ↓
④ 把 storyboard_nine.txt 貼進 ViralDNA（Chrome擴充功能）→ Google Flow 批次生圖   （手動）
   下載回來的是九宮格圖，存到 images-pre/，依序編號（0001, 0002...）
        ↓
④.5 scripts/split_images.py
   images-pre/ 的九宮格圖 → 切成 9 張（由左到右、由上到下）並放大到 1920×1080
   → images/0001.jpeg, 0002.jpeg...（每個 scene 一張）
        ↓
⑤ scripts/fetch_sfx.py
   storyboard.json → 自動抓音效（Freesound API + 本地音效庫）→ sfx_map.json
        ↓
⑥ scripts/build_video.py
   storyboard.json + images/ + 旁白音檔 + sfx_map.json → 最終 .mp4
   （前段分鏡預設做 zoom 動態效果，增加 retention，可用參數調整或關閉）
        ↓
⑦ scripts/json_to_srt.py（可選，字幕檔）
   storyboard.json → 校正過的 .srt 字幕檔，給剪輯軟體用
```

每一集（每一支影片）獨立放在 `episodes/<集數>/` 底下，`scripts/`、`assets/`、`docs/` 是跨集數共用的東西。

> `split_prompts.py` 和 `fetch_commons_images.py` 目前沒有用在主流程裡，功能說明見文末「暫時沒用到的腳本」。

---

## 資料夾結構

```
curious-charlie/
├── scripts/                          共用 Python 腳本（見下方詳細說明）
│   ├── extract_prompts_nine.py       主流程（預設）：storyboard.json → 九宮格漫畫 prompt
│   ├── extract_prompts_four.py       備用：storyboard.json → 四宮格漫畫 prompt
│   ├── split_images.py               主流程：宮格圖 → 單張圖（預設 3x3，可用參數改 2x2）
│   ├── fetch_sfx.py
│   ├── build_video.py
│   ├── json_to_srt.py
│   ├── split_prompts.py              （暫時沒用到）
│   └── fetch_commons_images.py       （暫時沒用到）
├── assets/
│   ├── character_reference/          主角人設參考圖（給人工檢查風格一致性用，不會被腳本讀取）
│   │   ├── Charlie_bold.png
│   │   └── Charlie_hair.jpeg
│   └── sound_effect/                 敘事節奏音效庫（手動挑選、CC0/已購買授權的固定音效檔）
│       ├── pop bright.mp3
│       ├── record scratch.mp3
│       ├── small bell ding.mp3
│       └── ...（其餘節奏音效，檔名需跟 storyboard.json 的 sfx_keyword 完全一致）
├── docs/
│   ├── storyboard-prompt-guide.md    給 Claude 看的分鏡製作方法論（怎麼把SRT轉成storyboard.json）
│   └── Visual_Style_Profile_*.md     視覺風格指南（美術風格、色票、角色設計）
├── episodes/
│   └── 000_短標題/                   每一支影片一個資料夾，命名格式：<三位數編號>_<短標題>
│       ├── storyboard.json           分鏡主控檔（本集資料的核心，其他檔案都是從這個產生或消費）
│       ├── storyboard_nine.txt       給 ViralDNA 貼的九宮格 prompt（extract_prompts_nine.py 產生）
│       ├── storyboard_four.txt       （改用四宮格時才有）extract_prompts_four.py 產生
│       ├── images-pre/               ViralDNA/Google Flow 產出的宮格原圖（依序編號）
│       ├── images/                   split_images.py 切割後的單張圖（0001.jpeg, 0002.jpeg...，1920×1080）
│       ├── archival_photos/          （暫時沒用到）fetch_commons_images.py 抓的 Wikimedia Commons 歷史照片
│       │   └── download_log.json     每張圖對應的來源、標題、授權紀錄，供人工審核
│       ├── sfx/                      fetch_sfx.py 抓下來的「內容音效」+ fetch_report.json（來源紀錄）
│       ├── sfx_map.json              fetch_sfx.py 產生，scene_id → 音效檔路徑對照表
│       ├── narration.mp3             完整旁白錄音
│       └── output/
│           └── narration_影片.mp4    build_video.py 最終輸出的成品影片
├── .env                              存放 FREESOUND_API_KEY（不可上傳到 GitHub，已在 .gitignore）
└── .gitignore
```

**每一集的 `images-pre/`、`images/`、`sfx/` 都是獨立的**，不同集數之間不共用。

---

## 事前準備（Prerequisites）

### 1. 安裝 FFmpeg

`build_video.py` 靠 FFmpeg 做影片合成，一定要先裝好，且要能在終端機直接打 `ffmpeg` 指令：

```bash
# macOS
brew install ffmpeg

# 確認安裝成功
ffmpeg -version
```

### 2. 安裝 Python 套件

Python 需要 3.9 以上（`build_video.py` 的 `--zoom/--no-zoom` 用到 `argparse.BooleanOptionalAction`）。

```bash
pip install requests zhconv pillow --break-system-packages
```
（如果是用虛擬環境，不用加 `--break-system-packages`）

- `requests`：`fetch_sfx.py`、`fetch_commons_images.py` 呼叫外部 API 用
- `zhconv`：簡體轉繁體用（分鏡設計階段，Claude在寫storyboard.json時會用到）
- `pillow`：`split_images.py` 切割、放大圖片用

### 3. 申請 Freesound API Key

`fetch_sfx.py` 的「內容音效」自動搜尋功能需要這個。

1. 到 https://freesound.org 註冊帳號
2. 到 https://freesound.org/apiv2/apply/ 申請一組 API credential
3. 在專案根目錄的 `.env` 檔案裡填入：
   ```
   FREESOUND_API_KEY=你的金鑰
   ```
4. 每次要跑 `fetch_sfx.py` 前，先把它讀進環境變數（或用 `--api-key` 參數帶入）：
   ```bash
   export FREESOUND_API_KEY=$(grep FREESOUND_API_KEY .env | cut -d '=' -f2)
   ```

### 4. 準備節奏音效庫

`assets/sound_effect/` 資料夾裡要手動放入你自己挑好、授權沒問題的音效檔，
**檔名必須跟 storyboard.json 裡的 `sfx_keyword` 完全一致**（含空格），例如：
```
pop bright.mp3
record scratch.mp3
small bell ding.mp3
```
這些是用來配合「重點/疑問句/反轉/幽默」等敘事節奏的固定音效，跟畫面內容無關，所以不透過 API 現搜，直接從這裡拿。

---

## 使用流程（Step by Step）

步驟編號跟上面 Workflow 圖的 ①～⑦ 一致。
以下假設終端機已經 `cd` 進某一集的資料夾，例如：
```bash
cd episodes/000_短標題
```

### Step 1：產生 SRT 逐字稿（手動）

用 Buzz 從錄音檔產出 SRT 逐字稿。

### Step 2：產生 storyboard.json（AI輔助，非腳本）

把 SRT 逐字稿 + `docs/` 底下的視覺風格指南，一起貼給 Claude，並附上 `docs/storyboard-prompt-guide.md` 的內容（或直接說「請照這份指南幫我做分鏡」）。Claude 會產出 `storyboard.json`，存到目前這一集的資料夾裡。

**這份 JSON 是整條 pipeline 的核心**，後面所有腳本都是讀/寫這個檔案。欄位說明見 `docs/storyboard-prompt-guide.md`，簡單來說：

| 欄位 | 說明 |
|---|---|
| `scene_id` | 分鏡編號，從1開始 |
| `start` / `end` / `duration` | 這個分鏡的時間範圍（秒） |
| `text` | 分鏡合併後的文字，只給設計畫面時參考用 |
| `cues` | 原始SRT逐句時間戳+校正文字，**不合併**，字幕輸出用這個 |
| `image_prompt` | 英文，要拿去生圖的完整prompt |
| `sfx_keyword` | 音效關鍵字（可省略） |
| `sfx_type` | `"rhythm"` 代表節奏音效（從本地音效庫拿），不寫代表內容音效（打API搜） |
| `sfx_offset` | 音效在分鏡內第幾秒響起（可省略，預設0＝分鏡一開始） |

### Step 3：產生九宮格漫畫 prompt（預設）

```bash
python ../../scripts/extract_prompts_nine.py storyboard.json
```

這支腳本會：
- 依序取出每個分鏡的 `image_prompt`（缺 `image_prompt` 的分鏡以 `empty` 代替）
- 每 9 個一組，最後一組不足 9 個就用 `empty` 補齊
- 每組輸出成一行，格式為開頭指令 + `Top-left: … Top-center: … Top-right: … Middle-left: … Middle-center: … Middle-right: … Bottom-left: … Bottom-center: … Bottom-right: …`
- 開頭指令要求畫成 3×3 九宮格，並加上「不要畫格子編號、標籤或說明文字」，避免圖上出現 (1)～(9) 之類的數字
- 組與組之間用換行分隔，不印在終端機

**輸出**：`storyboard_nine.txt`（跟輸入的 JSON 同資料夾）。例如 27 個分鏡會得到 3 行，第 N 行對應 scene N×9-8 ～ N×9。

格子位置對應：

| | 左 | 中 | 右 |
|---|---|---|---|
| 上 | Panel 1 | Panel 2 | Panel 3 |
| 中 | Panel 4 | Panel 5 | Panel 6 |
| 下 | Panel 7 | Panel 8 | Panel 9 |

**改用四宮格（2×2）**：

```bash
python ../../scripts/extract_prompts_four.py storyboard.json
```
輸出 `storyboard_four.txt`，每 4 個分鏡一行，順序為左上、右上、左下、右下。後面 Step 4.5 切圖時要記得加 `2`。

### Step 4：生圖（手動）

把 `storyboard_nine.txt` 的內容貼進 ViralDNA（Chrome擴充功能），它會依「Enter換行」判斷每一行是一張圖，交給 Google Flow 批次生成。

生完之後批次下載，**存到這一集資料夾底下的 `images-pre/`**。副檔名 `.jpeg`、`.jpg`、`.png` 都可以，腳本是依**檔名排序**讀取的，所以檔名必須是 **4位數零補位**、順序對應 `storyboard_nine.txt` 的行號：
```
images-pre/0001.jpg    ← storyboard_nine.txt 第 1 行（scene 1～9）
images-pre/0002.jpg    ← storyboard_nine.txt 第 2 行（scene 10～18）
...
```
每一張都是 3×3 的九宮格漫畫。

### Step 4.5：分割宮格圖（預設 3×3）

```bash
python ../../scripts/split_images.py
```

改用四宮格時，加參數 `2`：

```bash
python ../../scripts/split_images.py 2
```

這支腳本會：
1. 讀取 `images-pre/` 裡所有 `.jpeg` / `.jpg` / `.png`（依檔名排序）
2. 依參數把每張圖切成 N×N 塊（預設 N=3），順序：由左到右、由上到下
3. 每塊放大到 1920×1080（LANCZOS 插值，JPEG 品質 95）
4. 存到 `images/`（不存在會自動建立），一律輸出為 `.jpeg`，檔名連續編號

編號規則（3×3）：`images-pre/0001` 切出 `images/0001～0009.jpeg`，`images-pre/0002` 切出 `0010～0018.jpeg`，以此類推。`images/0001.jpeg` 對應 `scene_id: 1`。

**注意**：
- 不會裁掉宮格之間的分隔線，切出來的圖邊緣可能帶一點白邊和黑線
- 腳本用相對路徑，一定要在該集資料夾（`images-pre/` 的上一層）執行
- 重跑會覆蓋 `images/` 裡同名的檔案；如果 `images/` 裡有舊的（例如之前 2×2 切出來的），先改名或清空，避免新舊混在一起
- 切格數（3 或 2）要跟 Step 3 用的 extract 腳本一致，否則圖跟 scene 會對不上

### Step 5：抓音效

```bash
export FREESOUND_API_KEY="你的金鑰"
python ../../scripts/fetch_sfx.py --storyboard storyboard.json --output-dir sfx
```

這支腳本會：
- 讀 `storyboard.json` 裡每個有 `sfx_keyword` 的分鏡
- `sfx_type: "rhythm"` 的 → 去 `assets/sound_effect/`（預設路徑）找同名檔案
- 其他的（內容音效）→ 呼叫 Freesound API，自動下載排名第一、CC0授權、20秒以內的結果
- 全部結果合併輸出成 `sfx_map.json`（`scene_id → 音效檔路徑`）
- 額外產生 `sfx/fetch_report.json`，記錄每個音效的來源（名稱/授權/Freesound網頁連結），方便日後追查

**常用參數**：
| 參數 | 預設值 | 說明 |
|---|---|---|
| `--output-dir` | `sfx` | 內容音效下載存放資料夾 |
| `--rhythm-dir` | `../../assets/sound_effect` | 節奏音效庫路徑 |
| `--max-duration` | `20` | 內容音效搜尋時排除超過幾秒的結果 |
| `--sfx-map-output` | `sfx_map.json` | 輸出的對照表檔名 |

跑完如果有分鏡沒抓到音效，終端機會列出清單，把 `sfx_keyword` 換成更通用的英文詞再重跑即可（重跑不影響已抓到的分鏡）。

### Step 6：合成影片

```bash
python ../../scripts/build_video.py \
  --storyboard storyboard.json \
  --images-dir images \
  --narration narration.mp3 \
  --sfx-map sfx_map.json
```

預設是**前 60 秒的分鏡做 zoom**。想改成前 120 秒，加 `--zoom-until 120`；想完全不要 zoom，加 `--no-zoom`：

```bash
# 前 120 秒做 zoom
python ../../scripts/build_video.py \
  --storyboard storyboard.json \
  --images-dir images \
  --narration narration.mp3 \
  --sfx-map sfx_map.json \
  --zoom-until 120

# 完全不做 zoom（最快）
python ../../scripts/build_video.py \
  --storyboard storyboard.json \
  --images-dir images \
  --narration narration.mp3 \
  --sfx-map sfx_map.json \
  --no-zoom
```

> 多行指令每一行結尾（最後一行除外）都要加 `\`，漏掉的話 zsh 會把後面的參數當成另一個指令，出現 `command not found: --zoom-until`，參數也不會生效。

這支腳本會：
1. 檢查每個分鏡的圖片是否齊全（缺圖會自動用鄰近分鏡的圖頂替，並印出報告，不會中斷）
2. 把圖片依 `duration` 串接成影片（預設 1920x1080，30fps）：開始時間小於 `--zoom-until` 的分鏡各自做 zoom 片段，其餘分鏡用快速路徑一次編碼，最後用 `-c copy` 接起來
3. 把音效疊上旁白：截斷長度、正規化音量、句尾淡出、依 `sfx_offset` 對齊時間點
4. 輸出到 `output/narration_影片.mp4`

**常用參數**：
| 參數 | 預設值 | 說明 |
|---|---|---|
| `--output-dir` | `output` | 輸出資料夾 |
| `--strict` | 關閉 | 開啟後缺圖會直接報錯中斷，而不是頂替 |
| `--zoom` / `--no-zoom` | 開啟 | zoom 總開關，`--no-zoom` 優先權最高 |
| `--zoom-until` | `60` | 只對「開始時間 < 這個秒數」的分鏡做 zoom，之後走快速路徑 |
| `--max-zoom` | `1.05` | 最大縮放倍率（1.05 即放大 5%） |
| `--zoom-seconds` | `1.0` | 每個分鏡 zoom 動作的持續秒數，之後畫面靜止 |
| `--max-sfx-seconds` | `4.0` | 單個音效最長播放秒數 |
| `--sfx-volume-db` | `-8.0` | 音效相對旁白的音量（負值變小聲） |
| `--sfx-fade-seconds` | `0.3` | 音效結尾淡出秒數 |
| `--width` / `--height` / `--fps` | `1920`/`1080`/`30` | 輸出影片規格 |

#### Zoom 效果說明

目的是在影片前段增加畫面動態，幫助 retention。

- **動作**：每個 zoom 分鏡在前 `--zoom-seconds` 秒做一次餘弦緩動的縮放，之後畫面靜止。
- **方向**：放大（1.0 → `--max-zoom`）和縮小（`--max-zoom` → 1.0）逐張交替，縮放中心固定在畫面正中央。
- **範圍**：以「分鏡開始時間 < `--zoom-until`」判斷，整個分鏡要嘛全 zoom、要嘛全不 zoom，不會在分鏡中間切換，所以實際 zoom 範圍可能比設定值多出最後一個分鏡的長度。
- **速度**：zoom 的分鏡要各自跑一次 FFmpeg，比快速路徑慢很多。`--zoom-until` 越小越快，`--no-zoom` 最快。
- **確認有生效**：跑的時候終端機會印出「Zoom：前 N 個分鏡（開始時間 < X 秒）；其餘 M 個分鏡走快速路徑」，看這行的 X 就知道實際用的設定。
- **接合點**：zoom 片段和快速路徑片段用 `-c copy` 接起來，編碼參數已統一；如果成品在交接點（約 `--zoom-until` 秒處）有卡頓，需要把最後的接合步驟改成重新編碼。

跑完如果有分鏡是用頂替圖片做的，終端機最後會提醒你，補完正確的圖後重跑同一條指令即可覆蓋輸出。

### Step 7（可選）：產生校正後字幕

```bash
python ../../scripts/json_to_srt.py storyboard.json corrected.srt
```
把 `storyboard.json` 裡每個分鏡的 `cues`（原始SRT逐句時間戳+已校正文字）攤平輸出成 `.srt`，給剪輯軟體燒字幕用。字幕顆粒度維持跟原始SRT一樣密集，不會因為分鏡合併而變成一大句擠在一起。

---

## 暫時沒用到的腳本

以下兩支腳本還留在 `scripts/` 裡，但目前主流程沒有用到。

### `split_prompts.py`

```bash
python ../../scripts/split_prompts.py storyboard.json prompts.txt
```
把每個分鏡的 `image_prompt` 逐行輸出成 `prompts.txt`（每行一個 prompt，無空行，順序對應 scene_id），貼進 ViralDNA 後一行生一張單圖。目前已被 `extract_prompts_nine.py`（九宮格版）取代。如果要改回「一個 prompt 一張圖」的做法，用這支，且生出來的圖直接放 `images/`，不需要 Step 4.5 的分割。

### `fetch_commons_images.py`

如果某一集有分鏡適合用真實史料（人物肖像、歷史事件照、文件掃描），可以額外跑：

```bash
python ../../scripts/fetch_commons_images.py "Robert Owen portrait,Sykes-Picot Agreement map" --output-dir archival_photos
```

這支腳本會：
- 針對每個關鍵字去 Wikimedia Commons 搜尋
- 只收 **Public Domain 或 CC0** 授權的圖（CC-BY、CC-BY-SA 一律排除，因為需要標出處或有 ShareAlike 限制）
- 每個關鍵字最多下載 3 張，存到這一集資料夾底下的 `archival_photos/`，檔名格式：`keyword_1.jpg`、`keyword_2.jpg`...
- 同時產生 `archival_photos/download_log.json`，記錄每張圖的 Commons 標題、授權、來源連結，方便人工審核

抓完之後**人工檢查** `archival_photos/` 裡的圖片是否正確（例如標題誤植的肖像），確認沒問題的留著，錯的直接刪掉檔案。

**使用前設定**：依 Wikimedia API 規範，User-Agent 要能追溯到使用者。打開 `scripts/fetch_commons_images.py`，把 `HEADERS` 裡的 `YOUR_EMAIL_HERE` 換成你自己的信箱或聯絡方式，只需設定一次。

> 這支腳本是獨立工具，關鍵字要自己手動想、手動輸入，還沒有串接進 `storyboard.json` 或 `build_video.py`——`build_video.py` 不會自動去讀 `archival_photos/` 裡的圖片。要用的話，審核完覺得某張圖適合取代某個分鏡，手動把該分鏡在 `images/` 裡的圖換成這張即可。

---

## 各腳本速查表

| 腳本 | 輸入 | 輸出 | 用途 |
|---|---|---|---|
| `extract_prompts_nine.py`（預設） | `storyboard.json` | `storyboard_nine.txt` | 每 9 個 `image_prompt` 合併成一組九宮格漫畫 prompt，給 ViralDNA 生圖 |
| `extract_prompts_four.py` | `storyboard.json` | `storyboard_four.txt` | 每 4 個 `image_prompt` 合併成一組四宮格漫畫 prompt |
| `split_images.py` | `images-pre/` 的宮格圖 | `images/` 的單張圖（1920×1080） | 把宮格圖切成單張並放大；預設 3×3，加參數 `2` 切 2×2 |
| `fetch_sfx.py` | `storyboard.json` + Freesound API + 本地音效庫 | `sfx_map.json`、`sfx/`資料夾 | 自動抓音效（內容音效打API，節奏音效拿本地檔） |
| `build_video.py` | `storyboard.json` + `images/` + 旁白 + `sfx_map.json` | `output/*.mp4` | 合成最終影片（前段分鏡可做 zoom，`--zoom-until` 控制範圍） |
| `json_to_srt.py` | `storyboard.json` | `.srt` | 輸出校正後字幕檔 |
| `split_prompts.py`（暫時沒用到） | `storyboard.json` | `prompts.txt` | 每個 `image_prompt` 一行，一行一張單圖 |
| `fetch_commons_images.py`（暫時沒用到） | 關鍵字（逗號分隔） | `archival_photos/` 資料夾 + `download_log.json` | 抓 Wikimedia Commons 上 Public Domain/CC0 授權的歷史照片 |

---

## 常見問題

**Q: 宮格圖切出來，有些圖出現 (1)、(2) 之類的編號？**
模型把格子編號當成要畫進圖裡的內容。`extract_prompts_nine.py` 的開頭指令已經明確要求不要畫編號和標籤，但不保證 100% 消失。出現編號的那一組，回 ViralDNA 單獨重新生成，再重跑 Step 4.5。

**Q: 缺圖怎麼辦？**
`build_video.py` 預設會自動用鄰近分鏡的圖片頂替，並在終端機列出缺哪些 `scene_id` 跟對應的 `image_prompt`。因為是整組一起生成，補圖時要重新生成該 scene 所在的那一組（3×3 時對應 `storyboard_nine.txt` 的那一行，包含 9 個分鏡），下載後放進 `images-pre/`，重跑 Step 4.5 再重跑 Step 6。

**Q: 九宮格切出來的圖比四宮格糊？**
會。每一格的像素只有整張圖的 1/9（四宮格是 1/4），放大到 1920×1080 時解析度落差較大。生圖盡量選 2K 以上的輸出；如果畫質不夠，改用 `extract_prompts_four.py` + `split_images.py 2`。

**Q: 九宮格後面幾格的風格跑掉、或畫得很糊？**
每句 `image_prompt` 都帶完整風格句，9 格合在一行會很長（約 600～750 字），可能被截斷或稀釋。可以改用四宮格，或把風格句從每格抽出來，只在開頭指令放一次。

**Q: `split_images.py` 說找不到檔案？**
確認是在該集資料夾（`images-pre/` 的上一層）執行，而且 `images-pre/` 裡的副檔名是 `.jpeg`、`.jpg`、`.png` 之一。

**Q: 加了 `--zoom-until 120`，但只有前 60 秒有 zoom？**
先檢查指令換行：除了最後一行，每一行結尾都要有 `\`。漏掉的話，`--zoom-until 120` 會被 shell 當成另一個指令（`command not found: --zoom-until`），腳本就用預設的 60 秒在跑。另外看終端機印出的「Zoom：前 N 個分鏡（開始時間 < X 秒）」，X 不是你設的值就代表參數沒傳進去。

**Q: Zoom 讓合成變很慢？**
zoom 分鏡要逐張各跑一次 FFmpeg（內部用 2 倍解析度做 zoompan），所以慢。縮小 `--zoom-until`（例如 30）或加 `--no-zoom` 就會變快；zoom 範圍之外的分鏡走快速路徑，不受影響。

**Q: 音效聽起來忽大忽小/太大聲？**
`build_video.py` 已經對每個音效做過音量正規化（`dynaudnorm`）跟統一調降（預設 `-8dB`）。如果還是覺得不夠小聲，加大負值，例如 `--sfx-volume-db -12`。

**Q: 抓到的音效太長，蓋掉整段影片？**
不會發生——`build_video.py` 會自動把每個音效截斷到「該分鏡剩餘時長」跟 `--max-sfx-seconds`（預設4秒）兩者取較短的那個。

**Q: 為什麼節奏音效要手動準備，不直接用 Freesound 搜？**
測試過 Freesound 上「叮」「咻」這類通用音效庫存品質落差很大、不穩定。節奏音效需要全片風格一致（同一種反轉語氣都用同一個 record scratch），所以改成手動挑選、存在 `assets/sound_effect/` 固定使用。

**Q: Freesound 抓到的音效可以商用嗎？**
`fetch_sfx.py` 只搜尋 **CC0（公共領域）授權**的音效，完全不需要標示來源，可以放心商用。

**Q: `fetch_commons_images.py` 抓下來的歷史照片可以商用嗎？**
只收 **Public Domain 或 CC0** 授權，不需要標示來源，可以放心商用。CC-BY、CC-BY-SA 因為要標出處（CC-BY-SA 還多一條 ShareAlike 限制），腳本已經直接排除，不會出現在下載結果裡。

---

## 給下一個接手這個專案的人

如果要開新的一集，複製 `episodes/000_短標題/` 的資料夾結構（不用複製裡面的檔案），重新從 Step 1 開始跑一輪即可。`scripts/`、`assets/`、`docs/` 不用重新設定，是所有集數共用的。

如果需要重新產生 `storyboard.json`（例如換一支全新的影片），把新的 SRT + `docs/` 裡的視覺風格指南 一起貼給 Claude，並請它讀取 `docs/storyboard-prompt-guide.md` 的方法論來執行——那份文件記錄了完整的分鏡設計規則，不需要重新解釋一次。