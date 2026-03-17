# Ticket Debugger

OCR Pipeline Inspector — 用於檢視 OCR pipeline 產出的 ticket 資料，包括圖片、OCR 辨識框、表格資料與欄位資料。

## 架構

- **後端**: FastAPI + uvicorn，單檔 `server.py`，port 9020
- **前端**: 單頁 HTML (`static/index.html`)，vanilla JS，無框架
- **部署**: GitHub repo → server 上 `bash deploy.sh` 拉取並重啟

## 關鍵檔案

| 檔案 | 說明 |
|------|------|
| `server.py` | FastAPI 後端，IP 隔離上傳、session 管理、API routes |
| `static/index.html` | 完整前端 UI（CSS + HTML + JS 全在同一檔案） |
| `deploy.sh` | 部署腳本：git pull + kill old process + restart |

## 資料結構

### config.json 中的 integrator 有兩種格式
- **Dict 格式** (FERRARI): `integrator: { areaList, tableList }`
- **List 格式** (其他專案): `integrator: [{ areaList, tableList, type, ... }]`

後端已統一處理兩種格式。

### OCR 座標系
- `regList[].analyzer.areaList` 的 x/y/w/h 座標基於 `inputList`（processor 圖片）
- 前端顯示 `oriInputList`（原始圖片），需按比例換算座標
- `processorImgSize` 非同步載入，座標換算需等 processor 圖片 onload 後才正確

### 資料欄位座標
- `integrator.areaList[]` 和 `integrator.tableList[].data[][].cellList[]` 均包含 x/y/w/h 座標和 regNdx（頁碼）
- 座標 `(0,0,1,1)` 視為無效位置，不可定位
- 後端 `get_ticket()` 回傳 areas 和 table cells 時均包含座標欄位

## API Routes

| Method | Path | 說明 |
|--------|------|------|
| GET | `/` | 前端頁面 |
| POST | `/api/upload` | 上傳 ticket 資料夾（單一或批次） |
| POST | `/api/heartbeat` | 保持 session |
| GET | `/api/tickets` | 列出所有 ticket |
| GET | `/api/tickets/{id}` | 取得 ticket 詳細資料（含 areas、tables、pages） |
| PUT | `/api/tickets/{id}/config` | 更新 ticket 的 config.json |
| DELETE | `/api/tickets/{id}` | 刪除單一 ticket |
| DELETE | `/api/tickets` | 刪除所有 ticket |
| GET | `/api/tickets/{id}/pages/{idx}/areas` | 取得頁面 OCR areaList |
| GET | `/tickets/{id}/images/{filename}` | 取得 ticket 圖片 |

## Session 管理

- 每個 IP 獨立上傳空間（`uploads/{safe_ip}/`）
- 前端每 5 秒發送 heartbeat
- 後端每天凌晨 1:00 清理超過 24 小時無活動的 IP 資料

## UI 設計

- Dark OLED 主題，藍色主色 + 琥珀色/金黃色強調
- 字體: Fira Code (monospace) + Fira Sans (sans-serif)
- 首頁: feature cards (2×2)，點擊標題返回
- Sidebar: ticket 列表含 project（金黃）/ type（紫）/ result（OK/ERR）標籤
- 三個 Tab: Overview、Images、Table Data
- Image Viewer: transform-based zoom/pan，OCR overlay 座標換算

### Images Tab 功能
- Show OCR Areas / Show OCR Texts 切換
- Table-Image Position 切換：點擊 table cell 或 field 自動啟用，定位到圖片對應位置
- OCR 文字搜尋：支援跨頁搜尋，優先導航至離當前頁最近的結果

### Table Data Tab 功能
- Fields (areaList) 以 key-value grid 顯示，可定位到圖片
- Table (tableList) 含欄位顯示/隱藏切換
- 搜尋：支援大小寫敏感 (Aa) 和完全符合 (ab) 選項，VS Code 風格 toggle 按鈕
- 修改欄位顯示：原始文字紅色 + 修正文字綠色
- 空資料表（單行全空 + 座標 0,0,1,1）顯示 "empty row"
- 可點擊 cell/field 定位至圖片位置（Table-Image Position）

## 開發注意事項

- 前端全部在 `static/index.html` 一個檔案中，修改時注意 CSS/HTML/JS 三區塊
- 新增 ticket 格式時需同時修改 `server.py` 的 `get_ticket()` 和前端的 `renderTable()`
- 圖片座標換算邏輯在前端 `renderAreaOverlays()` 和 `renderCellHighlight()` 中
- Table 搜尋框為動態渲染（在 `renderTable()` 中），事件監聽器需在每次 render 後重新綁定
- `fetchJSON()` 使用 `cache: 'no-store'` 防止瀏覽器快取導致更新 config 後資料未刷新
- Config 更新後直接重新 fetch 資料並 re-render，不透過 `selectTicket()`
