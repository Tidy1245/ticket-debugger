"""Ticket Debugger - FastAPI Backend Server (IP-isolated uploads)"""

import asyncio
import base64
import io
import json
import shutil
import struct
import time
from pathlib import Path
from typing import List

import httpx
from PIL import Image
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

VLM_URL = "http://192.168.0.37:5070/v1/chat/completions"
VLM_MODEL = "/MODULE/peter/models/Qwen3-VL-30B-A3B-Instruct"
VLM_TIMEOUT = 300  # seconds

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Track last activity per IP for auto-cleanup
SESSION_TIMEOUT = 24 * 60 * 60  # 24 hours (cleanup runs daily at 1 AM)
ip_last_active: dict[str, float] = {}

app = FastAPI(title="Ticket Debugger")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_ip(request: Request) -> str:
    """Get client IP, supporting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


def ip_dir(ip: str) -> Path:
    """Get the upload directory for an IP."""
    safe_ip = ip.replace(":", "_").replace(".", "_")
    d = UPLOAD_DIR / safe_ip
    d.mkdir(parents=True, exist_ok=True)
    return d


def touch_ip(ip: str):
    """Update last active timestamp for an IP."""
    ip_last_active[ip] = time.time()


def cleanup_ip(ip: str):
    """Remove all uploads for an IP."""
    d = ip_dir(ip)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    ip_last_active.pop(ip, None)


async def cleanup_loop():
    """Background task to clean up expired sessions daily at 1 AM."""
    while True:
        # Calculate seconds until next 1:00 AM
        now = time.time()
        import datetime
        dt_now = datetime.datetime.fromtimestamp(now)
        target = dt_now.replace(hour=1, minute=0, second=0, microsecond=0)
        if dt_now >= target:
            target += datetime.timedelta(days=1)
        wait_seconds = (target - dt_now).total_seconds()
        await asyncio.sleep(wait_seconds)

        # Clean up all IPs that haven't been active for SESSION_TIMEOUT
        now = time.time()
        expired = [ip for ip, ts in ip_last_active.items() if now - ts > SESSION_TIMEOUT]
        for ip in expired:
            cleanup_ip(ip)


@app.on_event("startup")
async def start_cleanup():
    asyncio.create_task(cleanup_loop())


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/heartbeat")
async def heartbeat(request: Request):
    """Keep session alive."""
    ip = get_ip(request)
    touch_ip(ip)
    return {"ok": True}


@app.post("/api/upload")
async def upload_ticket(request: Request, files: List[UploadFile] = File(...)):
    """Upload a ticket folder."""
    if not files:
        raise HTTPException(400, "No files uploaded")

    ip = get_ip(request)
    touch_ip(ip)
    base = ip_dir(ip)
    ticket_id = None
    saved_files = []

    for f in files:
        rel_path = f.filename.replace("\\", "/")
        parts = rel_path.split("/")
        if ticket_id is None:
            ticket_id = parts[0]

        dest = base / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await f.read()
        dest.write_bytes(content)
        saved_files.append(rel_path)

    return {"ticketId": ticket_id, "fileCount": len(saved_files)}


@app.put("/api/tickets/{ticket_id}/config")
async def update_config(request: Request, ticket_id: str, file: UploadFile = File(...)):
    """Update config.json for a ticket."""
    ip = get_ip(request)
    touch_ip(ip)
    ticket_dir = ip_dir(ip) / ticket_id
    if not ticket_dir.exists():
        raise HTTPException(404, "Ticket not found")
    content = await file.read()
    # Validate JSON
    try:
        json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON file")
    config_path = ticket_dir / "config.json"
    config_path.write_bytes(content)
    return {"updated": ticket_id}


@app.delete("/api/tickets/{ticket_id}")
async def delete_ticket(request: Request, ticket_id: str):
    """Delete a single ticket."""
    ip = get_ip(request)
    touch_ip(ip)
    ticket_dir = ip_dir(ip) / ticket_id
    if not ticket_dir.exists():
        raise HTTPException(404, "Ticket not found")
    shutil.rmtree(ticket_dir)
    return {"deleted": ticket_id}


@app.delete("/api/tickets")
async def delete_all_tickets(request: Request):
    """Delete all tickets for this IP."""
    ip = get_ip(request)
    touch_ip(ip)
    base = ip_dir(ip)
    count = 0
    if base.exists():
        for d in base.iterdir():
            if d.is_dir():
                shutil.rmtree(d)
                count += 1
    return {"deleted": count}


@app.get("/api/tickets")
async def list_tickets(request: Request):
    """List all uploaded ticket IDs for this IP."""
    ip = get_ip(request)
    touch_ip(ip)
    base = ip_dir(ip)
    if not base.exists():
        return []
    tickets = sorted(
        [d.name for d in base.iterdir() if d.is_dir()],
        reverse=True,
    )
    results = []
    for tid in tickets:
        config_path = base / tid / "config.json"
        summary = {"ticketId": tid}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                summary["name"] = data.get("name", "")
                summary["project"] = data.get("project", "")
                summary["result"] = data.get("result", -1)
                summary["expectType"] = data.get("expectType", "")
                summary["errorMsg"] = data.get("errorMsg", "")
            except Exception:
                pass
        results.append(summary)
    return results


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(request: Request, ticket_id: str):
    """Get full ticket config."""
    ip = get_ip(request)
    touch_ip(ip)
    config_path = ip_dir(ip) / ticket_id / "config.json"
    if not config_path.exists():
        raise HTTPException(404, "Ticket not found")
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = {
        "ticketId": data.get("ticketId"),
        "project": data.get("project"),
        "name": data.get("name"),
        "expectType": data.get("expectType"),
        "result": data.get("result"),
        "errorMsg": data.get("errorMsg"),
        "appList": data.get("appList", []),
        "inputList": data.get("inputList", []),
        "pdfPath": data.get("pdfPath"),
        "formId": data.get("formId"),
    }

    raw_integrator = data.get("integrator", {})
    # Normalize: if integrator is a list, merge all entries; if dict, wrap as single
    if isinstance(raw_integrator, list):
        integrator_list = raw_integrator
    else:
        integrator_list = [raw_integrator] if raw_integrator else []

    areas = []
    tables = []
    for integ in integrator_list:
        # Extract areaList key-value fields
        for area in integ.get("areaList", []):
            areas.append({
                "key": area.get("key", ""),
                "name": area.get("name", ""),
                "text": area.get("text", ""),
                "textOCR": area.get("textOCR", ""),
                "confidence": area.get("confidence", []),
                "confidenceOCR": area.get("confidenceOCR", []),
                "regNdx": area.get("regNdx"),
                "x": area.get("x", 0),
                "y": area.get("y", 0),
                "w": area.get("w", 0),
                "h": area.get("h", 0),
            })
        # Extract tableList
        for tbl in integ.get("tableList", []):
            headers = tbl.get("headerList", [])
            rows = []
            for row_cells in tbl.get("data", []):
                row = {}
                for cell in row_cells:
                    cell_data = {
                        "text": cell.get("text", ""),
                        "textModify": cell.get("textModify", ""),
                        "confidence": cell.get("confidence", []),
                        "isFormatError": cell.get("isFormatError", False),
                        "regNdx": cell.get("regNdx"),
                        "x": cell.get("x", 0),
                        "y": cell.get("y", 0),
                        "w": cell.get("w", 0),
                        "h": cell.get("h", 0),
                    }
                    # Include areaList if present (for multi-area/cross-page cells)
                    if cell.get("areaList"):
                        cell_data["areaList"] = [
                            {"regNdx": a.get("regNdx"), "x": a.get("x", 0), "y": a.get("y", 0), "w": a.get("w", 0), "h": a.get("h", 0)}
                            for a in cell["areaList"]
                        ]
                    row[cell["key"]] = cell_data
                rows.append(row)
            tables.append({
                "table": tbl.get("table"),
                "name": tbl.get("name"),
                "type": tbl.get("type"),
                "headers": headers,
                "rows": rows,
            })
    summary["areas"] = areas
    summary["tables"] = tables

    pages = []
    for i, reg in enumerate(data.get("regList", [])):
        page_info = {
            "index": i,
            "regId": reg.get("regId"),
            "pageNdx": reg.get("pageNdx"),
            "result": reg.get("result"),
            "finalImgList": reg.get("finalImgList", []),
            "inputList": [inp.get("path") for inp in reg.get("inputList", [])],
            "oriInputList": [inp.get("path") for inp in reg.get("oriInputList", [])],
        }
        analyzer = reg.get("analyzer", {})
        page_info["areaCount"] = len(analyzer.get("areaList", []))
        pages.append(page_info)
    summary["pages"] = pages

    return summary


@app.get("/api/tickets/{ticket_id}/pages/{page_index}/areas")
async def get_page_areas(request: Request, ticket_id: str, page_index: int):
    """Get analyzer areaList for a specific page."""
    ip = get_ip(request)
    touch_ip(ip)
    config_path = ip_dir(ip) / ticket_id / "config.json"
    if not config_path.exists():
        raise HTTPException(404, "Ticket not found")
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    reg_list = data.get("regList", [])
    if page_index < 0 or page_index >= len(reg_list):
        raise HTTPException(404, "Page not found")
    reg = reg_list[page_index]
    analyzer = reg.get("analyzer", {})
    return {
        "pageNdx": reg.get("pageNdx"),
        "regId": reg.get("regId"),
        "areaList": analyzer.get("areaList", []),
    }


@app.get("/tickets/{ticket_id}/images/{filename}")
async def get_image(request: Request, ticket_id: str, filename: str):
    """Serve ticket images."""
    ip = get_ip(request)
    touch_ip(ip)
    file_path = ip_dir(ip) / ticket_id / filename
    if not file_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(file_path, media_type="image/jpeg")


class VLMGroupingRequest(BaseModel):
    pageIndex: int = 0
    pages: list[int] = []  # multiple pages to analyze
    docType: str = ""
    columns: str = ""
    groupStart: str = ""
    groupEnd: str = ""
    notes: str = ""
    crossPage: bool = False


def _get_jpeg_size(path: Path) -> tuple[int, int]:
    """Get image dimensions without PIL."""
    with open(path, "rb") as f:
        data = f.read()
    # Try JPEG
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 1:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker == 0xC0 or marker == 0xC2:  # SOF0 or SOF2
                h = struct.unpack(">H", data[i + 5:i + 7])[0]
                w = struct.unpack(">H", data[i + 7:i + 9])[0]
                return w, h
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + length
    # Try PNG
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        w = struct.unpack(">I", data[16:20])[0]
        h = struct.unpack(">I", data[20:24])[0]
        return w, h
    return 0, 0


# --- VLM Check Answer ---

CHECK_PRESETS = {
    'BVLGARI': {
        'keywords': [['Tva', 'Code'], ['Country of origin:'], ['Commodity code:']],
        'skipColumns': ['Item_No'],
        'formatRules': """BVLGARI Import Invoice:
- Item1 (Code): digits under "Code" column. Ignore "Cde. xxxx Po No. Delivery xxxx".
- Item2 (Description): text with underscores below Item1, to before "Serial number" or "Commodity code". Multi-line.
- Item3 (Serial number): after "Serial number", alphanumeric. May be absent.
- U_Price: number under "Prix unit/Unit price"
- Qty: number under "Quantité/Qty"
- Unit: text under "UM" (e.g. PCE)
- Amount: number under "Prix/Price"
- Mf_Cty: 2-letter code after "Country of origin:"
- N_W: number after "Net Weight". If grams divide by 1000. May be absent.""",
        'columns': 'Item_No, Item1, Item2, Item3, U_Price, Qty, Unit, Amount, Mf_Cty, N_W',
    },
    'LVMH': {
        'keywords': [['Reference', 'Description'], ['Country of origin'], ['Serial']],
        'skipColumns': ['Item_No'],
        'formatRules': """LVMH Watch & Jewellery Import Invoice:
- Item1 (Reference): alphanumeric reference code (e.g. AB1234-567)
- Item2 (Description): product description text. Multi-line.
- Item3 (Serial number): serial number after "Serial". May be absent.
- U_Price: unit price number
- Qty: quantity number
- Unit: unit text (e.g. PCE)
- Amount: total amount number
- Mf_Cty: 2-letter country code after "Country of origin"
- N_W: net weight number. May be absent.""",
        'columns': 'Item_No, Item1, Item2, Item3, U_Price, Qty, Unit, Amount, Mf_Cty, N_W',
    },
    'BOUCHERON': {
        'keywords': [['Code', 'Description'], ['Lot Number'], ['Origin']],
        'skipColumns': ['Item_No'],
        'formatRules': """BOUCHERON Import Invoice:
- Item1 (Code): product code (letters + digits, e.g. JCO123)
- Item2 (Description): product description. Multi-line.
- Item3 (Lot Number): lot number. May be absent.
- U_Price: unit price number
- Qty: quantity number
- Unit: unit text
- Amount: total amount number
- Mf_Cty: origin country text or code
- N_W: net weight. May be absent.""",
        'columns': 'Item_No, Item1, Item2, Item3, U_Price, Qty, Unit, Amount, Mf_Cty, N_W',
    },
    'LV': {
        'keywords': [['MADE IN'], ['Item Code'], ['Reference']],
        'skipColumns': ['Item_No'],
        'formatRules': """Louis Vuitton Import Invoice:
- Item1 (Item Code): 6-character alphanumeric code
- Item2 (Reference): reference code
- Item3 (Description): product description. Multi-line.
- U_Price: unit price number
- Qty: quantity number
- Unit: unit text
- Amount: total amount number
- Mf_Cty: country from "MADE IN" line (2-letter code)
- N_W: net weight. May be absent.""",
        'columns': 'Item_No, Item1, Item2, Item3, U_Price, Qty, Unit, Amount, Mf_Cty, N_W',
    },
}


def filter_table_pages(reg_list: list, keywords: list[list[str]]) -> list[int]:
    """Filter pages that contain table data by checking OCR text for keywords.
    Each keyword group is a list of strings that must ALL appear on the page.
    A page matches if ANY keyword group is fully matched.
    """
    result = []
    for i, reg in enumerate(reg_list):
        areas = reg.get("analyzer", {}).get("areaList", [])
        page_text = " ".join(a.get("text", "") for a in areas).lower()
        for kw_group in keywords:
            if all(kw.lower() in page_text for kw in kw_group):
                result.append(i)
                break
    return result


def concat_images_b64(paths: list[Path]) -> str:
    """Vertically concatenate images using PIL, return base64."""
    images = [Image.open(p) for p in paths if p.exists()]
    if not images:
        return ""
    if len(images) == 1:
        buf = io.BytesIO()
        images[0].save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    max_w = max(img.width for img in images)
    total_h = sum(img.height for img in images)
    combined = Image.new("RGB", (max_w, total_h), (255, 255, 255))
    y_offset = 0
    for img in images:
        combined.paste(img, (0, y_offset))
        y_offset += img.height
    buf = io.BytesIO()
    combined.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def build_check_prompt(format_rules: str, columns: str, rows_text: str, skip_columns: list[str] | None = None) -> str:
    """Build the VLM check-answer prompt."""
    skip_note = ""
    if skip_columns:
        skip_note = f"\n- SKIP these columns (auto-generated, do NOT verify): {', '.join(skip_columns)}"
    return f"""You are verifying OCR pipeline output against the original document image.

Format rules for this document type:
{format_rules}

Columns: {columns}

The OCR pipeline extracted these rows:
{rows_text}

Compare ONLY the pipeline values against what you actually see in the document image.

Output JSON array. For each row:
{{"row": ROW_INDEX, "fields": [{{"col": "COLUMN_NAME", "status": "WRONG|MISSING", "expected": "correct value"}}]}}

IMPORTANT rules:
- ONLY report fields that are genuinely WRONG or MISSING. Omit correct fields.
- A field is CORRECT if the pipeline value matches the image value in meaning, even if formatting differs slightly (e.g. extra spaces, "1,234.00" vs "1234.00", trailing zeros, comma vs period in thousands).
- A field is WRONG only if the actual content/digits/letters are different from what the image shows.
- A field is MISSING only if the image clearly shows a value but the pipeline has it empty.
- ROW_INDEX must match the exact "Row N" index from the pipeline output above.
- If a row is entirely correct, include it with empty fields array: {{"row": N, "fields": []}}
- Do NOT invent values. Only report what you can clearly read from the image.{skip_note}
- Output ONLY the JSON array, no other text."""


class VLMCheckRequest(BaseModel):
    preset: str = ""
    customRules: str = ""
    columns: str = ""


@app.post("/api/tickets/{ticket_id}/vlm-check-answer")
async def vlm_check_answer(request: Request, ticket_id: str, body: VLMCheckRequest):
    """Run VLM-based answer checking via SSE stream."""
    ip = get_ip(request)
    touch_ip(ip)
    config_path = ip_dir(ip) / ticket_id / "config.json"
    if not config_path.exists():
        raise HTTPException(404, "Ticket not found")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reg_list = data.get("regList", [])
    ticket_dir = ip_dir(ip) / ticket_id

    # Get preset config or custom
    preset_cfg = CHECK_PRESETS.get(body.preset, {})
    format_rules = body.customRules or preset_cfg.get('formatRules', '')
    columns = body.columns or preset_cfg.get('columns', '')
    keywords = preset_cfg.get('keywords', [])
    skip_columns = preset_cfg.get('skipColumns', [])

    if not format_rules or not columns:
        raise HTTPException(400, "Format rules and columns are required")

    # Get integrator table rows
    raw_integrator = data.get("integrator", {})
    if isinstance(raw_integrator, list):
        integrator_list = raw_integrator
    else:
        integrator_list = [raw_integrator] if raw_integrator else []

    table_rows = []
    table_headers = []
    for integ in integrator_list:
        for tbl in integ.get("tableList", []):
            if not table_headers:
                table_headers = [h.get("key", "") for h in tbl.get("headerList", [])]
            for row_cells in tbl.get("data", []):
                row = {}
                for cell in row_cells:
                    key = cell.get("key", "")
                    row[key] = cell.get("textModify", "") or cell.get("text", "")
                    # Track regNdx for page association
                    if "regNdx" in cell:
                        row[f"_regNdx_{key}"] = cell["regNdx"]
                table_rows.append(row)

    if not table_rows:
        raise HTTPException(400, "No table data found in ticket")

    # Filter table pages using keywords
    if keywords:
        table_pages = filter_table_pages(reg_list, keywords)
    else:
        # Fallback: use pages that have table data (by regNdx)
        page_set = set()
        for row in table_rows:
            for k, v in row.items():
                if k.startswith("_regNdx_"):
                    page_set.add(v)
        table_pages = sorted(page_set)

    if not table_pages:
        # Use all pages as fallback
        table_pages = list(range(len(reg_list)))

    # Pair pages: every 2 pages concatenated
    pairs = []
    for i in range(0, len(table_pages), 2):
        if i + 1 < len(table_pages):
            pairs.append((table_pages[i], table_pages[i + 1]))
        else:
            pairs.append((table_pages[i],))

    # Map rows to page pairs by regNdx
    def get_row_pages(row):
        pages = set()
        for k, v in row.items():
            if k.startswith("_regNdx_"):
                pages.add(v)
        return pages

    async def event_stream():
        t0 = time.time()
        yield f"data: {json.dumps({'event': 'init', 'totalPairs': len(pairs), 'tablePages': table_pages, 'totalRows': len(table_rows), 'skipColumns': skip_columns})}\n\n"

        all_results = []

        async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
            for pi, pair in enumerate(pairs):
                pair_t0 = time.time()

                # Get image paths for this pair
                img_paths = []
                for page_idx in pair:
                    if page_idx < len(reg_list):
                        reg = reg_list[page_idx]
                        img_filename = reg.get("inputList", [{}])[0].get("path")
                        if img_filename:
                            img_path = ticket_dir / img_filename
                            if img_path.exists():
                                img_paths.append(img_path)

                if not img_paths:
                    all_results.append({"pairIndex": pi, "pages": list(pair), "rows": []})
                    elapsed = round(time.time() - t0, 1)
                    yield f"data: {json.dumps({'event': 'progress', 'pairIndex': pi, 'totalPairs': len(pairs), 'elapsed': elapsed, 'pairResults': []})}\n\n"
                    continue

                # Concatenate images
                img_b64 = concat_images_b64(img_paths)
                if not img_b64:
                    continue

                # Find rows belonging to this pair's pages
                pair_page_set = set(pair)
                pair_rows = []
                pair_row_indices = []
                for ri, row in enumerate(table_rows):
                    row_pages = get_row_pages(row)
                    if row_pages & pair_page_set or not row_pages:
                        pair_rows.append(row)
                        pair_row_indices.append(ri)

                if not pair_rows:
                    all_results.append({"pairIndex": pi, "pages": list(pair), "rows": []})
                    elapsed = round(time.time() - t0, 1)
                    yield f"data: {json.dumps({'event': 'progress', 'pairIndex': pi, 'totalPairs': len(pairs), 'elapsed': elapsed, 'pairResults': []})}\n\n"
                    continue

                # Build rows text (exclude skip columns)
                col_list = [c.strip() for c in columns.split(",")]
                check_cols = [c for c in col_list if c not in skip_columns]
                rows_text = ""
                for i, row in enumerate(pair_rows):
                    vals = []
                    for c in check_cols:
                        # Try exact key match, then case-insensitive
                        val = row.get(c, "")
                        if not val:
                            for k, v in row.items():
                                if not k.startswith("_regNdx_") and k.lower() == c.lower():
                                    val = v
                                    break
                        vals.append(f"{c}={val}" if val else f"{c}=")
                    rows_text += f"Row {pair_row_indices[i]}: {', '.join(vals)}\n"

                # Build prompt
                prompt = build_check_prompt(format_rules, columns, rows_text, skip_columns)

                # Call VLM
                try:
                    resp = await client.post(VLM_URL, json={
                        "model": VLM_MODEL,
                        "messages": [{"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                            {"type": "text", "text": prompt},
                        ]}],
                        "max_tokens": 4000,
                        "temperature": 0.1,
                    })
                    resp.raise_for_status()
                    content = resp.json()["choices"][0]["message"]["content"]

                    # Parse JSON response
                    js = content
                    if "```json" in content:
                        js = content.split("```json")[1].split("```")[0]
                    elif "```" in content:
                        js = content.split("```")[1].split("```")[0]
                    parsed = json.loads(js.strip())

                    # Normalize: ensure it's a list
                    if not isinstance(parsed, list):
                        parsed = [parsed]

                    pair_results = parsed
                except Exception as e:
                    pair_results = [{"error": str(e)}]

                all_results.append({"pairIndex": pi, "pages": list(pair), "results": pair_results})
                elapsed = round(time.time() - t0, 1)
                yield f"data: {json.dumps({'event': 'progress', 'pairIndex': pi, 'totalPairs': len(pairs), 'elapsed': elapsed, 'pairResults': pair_results})}\n\n"

        total_elapsed = round(time.time() - t0, 1)
        yield f"data: {json.dumps({'event': 'done', 'results': all_results, 'totalElapsed': total_elapsed})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/tickets/{ticket_id}/vlm-grouping")
async def vlm_grouping(request: Request, ticket_id: str, body: VLMGroupingRequest):
    """Run VLM-based table row grouping on a ticket page."""
    ip = get_ip(request)
    touch_ip(ip)
    config_path = ip_dir(ip) / ticket_id / "config.json"
    if not config_path.exists():
        raise HTTPException(404, "Ticket not found")

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    reg_list = data.get("regList", [])
    ticket_dir = ip_dir(ip) / ticket_id

    # Determine pages to process
    page_indices = body.pages if body.pages else [body.pageIndex]
    for pi in page_indices:
        if pi < 0 or pi >= len(reg_list):
            raise HTTPException(404, f"Page {pi} not found")

    # Build prompt context from hints
    context = f"This is a {body.docType}. " if body.docType else "This document has a product/item table. "
    if body.groupStart and body.groupEnd:
        context += f"Each group starts with {body.groupStart} and ends with {body.groupEnd}. "
    elif body.groupStart:
        context += f"Each group starts with {body.groupStart}. "
    elif body.groupEnd:
        context += f"Each group ends with {body.groupEnd}. "
    if body.columns:
        context += f"Columns: {body.columns}. "
    if body.notes:
        context += f"{body.notes}. "

    prompt_template = f"""{context}
How many product/item groups are in the table? For each group give its vertical position.
Output JSON: {{"image_height":H,"groups":[{{"group":1,"y_start":N,"y_end":N,"description":"short item description"}}]}}
Only JSON."""

    # Process each page
    t0 = time.time()
    all_groups = []
    total_areas = 0
    total_assigned = 0

    async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
        for pi in page_indices:
            reg = reg_list[pi]
            img_filename = reg.get("inputList", [{}])[0].get("path")
            if not img_filename:
                continue
            img_path = ticket_dir / img_filename
            if not img_path.exists():
                continue

            img_data = img_path.read_bytes()
            img_b64 = base64.b64encode(img_data).decode()
            _, img_h = _get_jpeg_size(img_path)
            areas = reg.get("analyzer", {}).get("areaList", [])
            total_areas += len(areas)

            # Call VLM
            try:
                resp = await client.post(VLM_URL, json={
                    "model": VLM_MODEL,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                        {"type": "text", "text": prompt_template},
                    ]}],
                    "max_tokens": 1500,
                    "temperature": 0.1,
                })
                resp.raise_for_status()
            except httpx.TimeoutException:
                raise HTTPException(504, f"VLM request timed out on page {pi + 1}")
            except Exception as e:
                raise HTTPException(502, f"VLM request failed on page {pi + 1}: {str(e)}")

            content = resp.json()["choices"][0]["message"]["content"]

            # Parse JSON
            try:
                js = content
                if "```json" in content:
                    js = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    js = content.split("```")[1].split("```")[0]
                parsed = json.loads(js.strip())
                if isinstance(parsed, list):
                    vlm_groups = parsed
                    vlm_img_h = 0
                else:
                    vlm_groups = parsed.get("groups", parsed.get("tables", []))
                    vlm_img_h = parsed.get("image_height", 0)
            except (json.JSONDecodeError, IndexError):
                continue  # Skip page on parse failure

            # Scale VLM coordinates
            scale_y = img_h / vlm_img_h if vlm_img_h and img_h else 1.0

            # Build scaled group boundaries
            scaled_groups = []
            for g in vlm_groups:
                y1 = g.get("y_start", 0) * scale_y
                y2 = g.get("y_end", 0) * scale_y
                scaled_groups.append({"y1": y1, "y2": y2, "mid": (y1 + y2) / 2, "desc": g.get("description", "")})

            if not scaled_groups:
                continue

            # Match OCR areas to NEAREST group by midpoint
            group_areas: dict[int, list] = {i: [] for i in range(len(scaled_groups))}
            assigned = set()
            overall_y1 = scaled_groups[0]["y1"]
            overall_y2 = scaled_groups[-1]["y2"]
            margin = (overall_y2 - overall_y1) * 0.05

            for i, area in enumerate(areas):
                if not area.get("text", "").strip():
                    continue
                cy = area.get("y", 0) + area.get("h", 0) / 2
                if cy < (overall_y1 - margin) or cy > (overall_y2 + margin):
                    continue
                best_gi, best_dist = -1, float("inf")
                for gi, sg in enumerate(scaled_groups):
                    dist = abs(cy - sg["mid"])
                    if dist < best_dist:
                        best_dist = dist
                        best_gi = gi
                if best_gi >= 0:
                    assigned.add(i)
                    group_areas[best_gi].append({
                        "areaId": i, "text": area.get("text", ""),
                        "x": area.get("x", 0), "y": area.get("y", 0),
                        "w": area.get("w", 0), "h": area.get("h", 0),
                    })

            total_assigned += len(assigned)
            for gi, sg in enumerate(scaled_groups):
                all_groups.append({
                    "index": len(all_groups),
                    "pageIndex": pi,
                    "y_start": sg["y1"], "y_end": sg["y2"],
                    "description": sg["desc"],
                    "areas": group_areas[gi],
                })

    elapsed = round(time.time() - t0, 1)
    return {
        "groups": all_groups,
        "elapsed": elapsed,
        "pages": page_indices,
        "totalAreas": total_areas,
        "assignedAreas": total_assigned,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9020)
