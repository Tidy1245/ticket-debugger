# Ticket Debugger

OCR Pipeline Inspector — 用於檢視 OCR pipeline 產出的 ticket 資料，包括圖片、辨識框、表格資料與欄位資料。

## 快速開始

```bash
# 安裝依賴
pip install fastapi uvicorn

# 啟動 server（預設 port 9020）
python server.py

# 瀏覽器開啟
http://localhost:9020
```

---

## UI 功能總覽

### 上傳 Ticket

拖曳或選取 ticket 資料夾上傳，支援批次上傳。上傳後左側 Sidebar 會列出所有 ticket，標籤顯示：

- **金黃** — 專案名稱
- **紫色** — 類型
- **綠色 OK / 紅色 ERR** — 辨識結果

---

### Tab 功能

#### Images — 圖片檢視

- 縮放 / 平移（transform-based），支援 scroll zoom
- **Show OCR Areas** / **Show OCR Texts** — 疊加顯示 OCR 辨識框與文字
- **Table-Image Position** — 點擊表格 cell 自動定位到圖片對應位置
- **OCR 文字搜尋** — 跨頁搜尋，自動導航至最近頁的結果

---

#### Table Data — 表格資料

- 上半部 **Fields**：`areaList` 欄位以 key-value grid 顯示
- 下半部 **Table**：`tableList` 以 HTML 表格顯示，支援欄位顯示/隱藏
- **搜尋**：支援大小寫敏感（Aa）/ 完全符合（ab）切換
- **Edit Mode**：直接編輯欄位值（contenteditable），確認後同步至 ticketData
- **匯出 config.json**：含當前編輯值的完整 config

---

#### Visual Check — 視覺核對

左右 1:1 並排：左側圖片、右側可折疊 card（Group View）。

- 點擊 card header → 展開並在圖片上高亮該組所有 cell（黃色框）
- 支援跨頁組（紫色框標示）
- **Edit Mode** + **Save as Answer** — 編輯後存為 Data Answer
- **複製 OCR 文字** — 點擊 OCR 區域複製文字到剪貼簿

---

#### Visual Table — 視覺表格

左圖右傳統表格，點擊即高亮，無需切換 tab。

- **Cell / Group 切換** — Cell 模式高亮單格；Group 模式高亮整行
- **左右拖曳調整**圖片與表格的寬度比例
- **滾輪方向切換** — 激活後滾輪改為左右滾動表格

---

#### VLM Grouping — VLM 表格分組

使用 Qwen3-VL-30B 分析表格結構，將 OCR items 分組為邏輯行。

- 可附加提示：文件類型、欄位名稱、分組模式
- 點擊分組結果 → 切換至 Images tab 並以紫色框高亮該組

---

#### VLM Answer — VLM 答案比對

兩步驟流程：

1. **VLM 讀取**：VLM 看圖產出結構化表格答案（SSE 串流）
2. **程式比對**：LCS 字串相似度演算法比對 pipeline vs VLM 答案，差異以紅/綠標示

- 支援內建 Preset + 自訂 Preset（各專案 keywords / columns 設定）
- VLM 答案持久化，可手動編輯、另存為 Data Answer

---

#### Data Mgmt — 資料管理

統一管理所有 Data Answer（來自 VLM、Visual Check 或手動輸入）。

- **CRUD**：新增、載入、儲存（含改名）、刪除
- **來源標籤**：`manual` / `visual-check` / `vlm-answer`
- Fields 編輯器（key-value）+ Table 編輯器（contenteditable 表格）

---

## 如何在 README 放上小動畫？

### 方法一：錄製 GIF（最簡單）

推薦工具：

| 工具 | 平台 | 免費 |
|------|------|------|
| **[ScreenToGif](https://www.screentogif.com/)** | Windows | 是 |
| **[Kap](https://getkap.co/)** | macOS | 是 |
| **[LICEcap](https://www.cockos.com/licecap/)** | Win/Mac | 是 |

錄製後放到專案的 `docs/` 資料夾，在 README 用：

```markdown
![功能展示](docs/demo-visual-check.gif)
```

---

### 方法二：錄製 MP4 → 上傳 GitHub

GitHub README 支援直接嵌入影片（`.mp4`、`.webm`）：

1. 在 GitHub issue 或 PR 的編輯框**直接拖曳 MP4 檔案**
2. GitHub 會自動上傳並產生連結如 `https://github.com/user-attachments/assets/xxx.mp4`
3. 複製連結貼到 README：

```markdown
https://github.com/user-attachments/assets/xxx.mp4
```

GitHub 會自動渲染為可播放的影片。

---

### 方法三：使用 asciinema（純 CLI 操作展示）

若要展示 server 啟動等 terminal 操作，可用 [asciinema](https://asciinema.org/) 錄製並嵌入。

---

### 建議的 GIF 規格

- 解析度：1280×720 或 1920×1080 縮小至 960×540
- 幀率：10–15 fps（檔案小，播放流暢）
- 時長：每段 5–15 秒，聚焦單一功能
- 工具推薦用 ScreenToGif 的「最佳化」功能壓縮到 < 5MB

---

## 架構

```
ticket-debugger/
├── server.py          # FastAPI 後端（port 9020）
├── static/
│   └── index.html     # 完整前端（CSS + HTML + JS 單檔）
├── deploy.sh          # 部署腳本
├── uploads/           # 上傳暫存（IP 隔離，24h 自動清理）
└── data/
    ├── vlm_answers/   # VLM 答案（持久化）
    ├── custom_presets/ # 自訂 Preset（持久化）
    └── data_answers/  # Data Answer（持久化）
```
