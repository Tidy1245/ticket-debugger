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
| POST | `/api/tickets/{id}/vlm-grouping` | VLM 表格分組（送圖片至 VLM server 分析） |
| POST | `/api/tickets/{id}/vlm-check-answer` | VLM 讀取圖片表格（SSE 串流，完成後自動存答案） |
| GET | `/api/vlm-answers/{id}` | 取得已存儲的 VLM 答案 |
| PUT | `/api/vlm-answers/{id}` | 儲存/更新 VLM 答案（含手動編輯） |
| DELETE | `/api/vlm-answers/{id}` | 刪除 VLM 答案 |
| GET | `/api/check-presets` | 列出所有 preset（內建 + 自訂） |
| POST | `/api/check-presets` | 新增自訂 preset |
| DELETE | `/api/check-presets/{name}` | 刪除自訂 preset |
| DELETE | `/api/tickets/{id}` | 刪除單一 ticket |
| DELETE | `/api/tickets` | 刪除所有 ticket |
| GET | `/api/tickets/{id}/pages/{idx}/areas` | 取得頁面 OCR areaList |
| GET | `/tickets/{id}/images/{filename}` | 取得 ticket 圖片 |
| GET | `/api/data-answers` | 列出所有 data answer（name, source, columns, fieldCount, rowCount） |
| GET | `/api/data-answers/{name}` | 讀取單一 data answer |
| PUT | `/api/data-answers/{name}` | 儲存/更新 data answer |
| DELETE | `/api/data-answers/{name}` | 刪除 data answer |

## 持久化存儲

- `uploads/` — IP 隔離的 ticket 上傳目錄，受 session timeout 清理
- `data/vlm_answers/` — VLM 答案 JSON，以 ticketId 為 key，不受 session 清理
- `data/custom_presets/` — 使用者自訂 preset JSON，不受 session 清理
- `data/data_answers/` — Data Answer JSON，統一答案管理，不受 session 清理

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

### VLM Grouping 功能
- 使用 Qwen3-VL-30B (vLLM) 分析表格結構，將 OCR items 分組為邏輯行
- VLM server: `http://192.168.0.37:5070`，OpenAI-compatible API
- 流程：送 processor 圖片 → VLM 回傳每組 Y 座標範圍 → 程式匹配 OCR areas
- 三個可選提示：文件類型、欄位名稱、分組模式
- VLM panel 獨立於 tableContent，不受 renderTable() 重繪影響
- 點擊分組結果會切換到 Images tab 並以紫色框高亮該組所有 areas

### Visual Check Tab 功能
- 左右 1:1 並排：左側圖片、右側表格資料，方便快速核對
- 圖片為 fit-width 顯示，滾輪上下滑動瀏覽
- 獨立頁面導航（`vcPageIndex`），不影響 Images tab 的 `currentPageIndex`
- 頁面導航右側顯示「當前頁組數 / 總組數」（0 組時不顯示）
- Fields 和每個 table row 各為一張可折疊 card（Group View）
  - 點擊 header → 展開 + 高亮該組所有 cell 到圖片上
  - 展開後每個 field 可單獨點擊高亮
- 跨頁支援：選取跨頁的組或欄位後，切頁時高亮持續顯示
- 跨頁組和欄位以紫色框標註（`.vc-cross-page`、`.vc-cross-page-field`）
- 座標換算簡化版：`x * img.clientWidth / processor.w`（fit-width 不需 zoom/pad）
- JS 函式群：`vcRender*`、`vcLoad*`、`vcHighlight*`、`vcBindGroupEvents`
- Edit Mode：啟用後所有欄位值可直接編輯（contenteditable），底部出現 "Save as Answer" 按鈕
- Save as Answer 會收集所有 fields 和 rows 存為 Data Answer（`source: "visual-check"`）

### VLM Answer 功能（原 VLM Check）
- 獨立 Tab「VLM Answer」，分兩步驟：VLM 讀取 → 程式比對
- **Step 1 - VLM 讀取**：VLM 只看圖產出結構化表格答案（不做比對），SSE 串流
- **Step 2 - 程式比對**：前端 LCS 字串相似度演算法比對 pipeline vs VLM 答案
- 比對顯示：雙行（Pipeline 綠字+紅色標差異 / VLM 淺綠字，缺失用黃色）
- VLM 答案持久化存在 `data/vlm_answers/`，可手動編輯、儲存、刪除
- Preset 支援內建（中文）+ 自訂（存在 `data/custom_presets/`），可新增/刪除
- `CHECK_PRESETS` 定義各專案的 keywords、formatRules、columns、skipColumns
- 前端 `renderCheckPanel()` 獨立於 `renderTable()`，在 `selectTicket()` 和 config 更新時呼叫
- 「另存為答案」按鈕可將 VLM 答案複製為 Data Answer（`source: "vlm-answer"`）

### Data Management Tab 功能
- 獨立 Tab「Data Mgmt」，統一管理所有 Data Answer
- 資料結構：`{ name, ticketId, fields: [{key, value}], rows: [{col: val}], columns, source }`
- 存儲：`data/data_answers/`，以 name 為檔名
- 來源標籤：`manual`（手動新增）、`visual-check`（從 VC 編輯模式）、`vlm-answer`（從 VLM 答案）
- Fields 編輯器：key-value grid，可新增/刪除
- Table 編輯器：contenteditable 表格，可新增/刪除 row
- CRUD 操作：新增、載入、儲存（含改名）、刪除
- JS 函式群：`renderDataPanel()`、`loadDataAnswersList()`、`loadDataAnswerByName()`、`dataCollectEdits()`

## 開發注意事項

- 前端全部在 `static/index.html` 一個檔案中，修改時注意 CSS/HTML/JS 三區塊
- 新增 ticket 格式時需同時修改 `server.py` 的 `get_ticket()` 和前端的 `renderTable()`
- 圖片座標換算邏輯在前端 `renderAreaOverlays()` 和 `renderCellHighlight()` 中
- Table 搜尋框為動態渲染（在 `renderTable()` 中），事件監聽器需在每次 render 後重新綁定
- `fetchJSON()` 使用 `cache: 'no-store'` 防止瀏覽器快取導致更新 config 後資料未刷新
- Config 更新後直接重新 fetch 資料並 re-render，不透過 `selectTicket()`
