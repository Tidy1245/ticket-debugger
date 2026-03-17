"""Ticket Debugger - FastAPI Backend Server (IP-isolated uploads)"""

import asyncio
import base64
import json
import shutil
import struct
import time
from pathlib import Path
from typing import List

import httpx
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
                    row[cell["key"]] = {
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
    if body.pageIndex < 0 or body.pageIndex >= len(reg_list):
        raise HTTPException(404, "Page not found")

    reg = reg_list[body.pageIndex]
    # Use processor image (inputList) - OCR coords are based on it
    img_filename = reg.get("inputList", [{}])[0].get("path")
    if not img_filename:
        raise HTTPException(400, "No image for this page")

    ticket_dir = ip_dir(ip) / ticket_id
    img_path = ticket_dir / img_filename
    if not img_path.exists():
        raise HTTPException(404, "Image file not found")

    # Read image + get dimensions
    img_data = img_path.read_bytes()
    img_b64 = base64.b64encode(img_data).decode()
    img_w, img_h = _get_jpeg_size(img_path)

    # Get OCR areas
    areas = reg.get("analyzer", {}).get("areaList", [])

    # Build prompt
    hints = []
    if body.docType:
        hints.append(f"Document type: {body.docType}")
    if body.columns:
        hints.append(f"Table columns: {body.columns}")
    if body.groupStart:
        hints.append(f"Each group starts with: {body.groupStart}")
    if body.groupEnd:
        hints.append(f"Each group ends with: {body.groupEnd}")
    if body.notes:
        hints.append(f"Additional info: {body.notes}")
    hints_str = "\n".join(hints)

    # Build targeted prompt
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

    prompt = f"""{context}
How many product/item groups are in the table? For each group give its vertical position.
Output JSON: {{"image_height":H,"groups":[{{"group":1,"y_start":N,"y_end":N,"description":"short item description"}}]}}
Only JSON."""

    # Call VLM
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
            resp = await client.post(VLM_URL, json={
                "model": VLM_MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": prompt},
                ]}],
                "max_tokens": 1500,
                "temperature": 0.1,
            })
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(504, "VLM request timed out")
    except Exception as e:
        raise HTTPException(502, f"VLM request failed: {str(e)}")

    elapsed = round(time.time() - t0, 1)
    content = resp.json()["choices"][0]["message"]["content"]

    # Parse JSON from response
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
        raise HTTPException(500, f"Failed to parse VLM response: {content[:500]}")

    # Scale VLM coordinates to real image coordinates
    scale_y = img_h / vlm_img_h if vlm_img_h and img_h else 1.0

    # Match OCR areas to groups by Y-coordinate
    groups = []
    assigned = set()
    for g in vlm_groups:
        y1 = g.get("y_start", 0) * scale_y
        y2 = g.get("y_end", 0) * scale_y
        margin = (y2 - y1) * 0.1  # 10% margin for tolerance
        desc = g.get("description", "")
        matched_areas = []
        for i, area in enumerate(areas):
            cy = area.get("y", 0) + area.get("h", 0) / 2
            if (y1 - margin) <= cy <= (y2 + margin) and i not in assigned:
                assigned.add(i)
                matched_areas.append({
                    "areaId": i,
                    "text": area.get("text", ""),
                    "x": area.get("x", 0),
                    "y": area.get("y", 0),
                    "w": area.get("w", 0),
                    "h": area.get("h", 0),
                })
        groups.append({
            "index": len(groups),
            "y_start": y1,
            "y_end": y2,
            "description": desc,
            "areas": matched_areas,
        })

    return {
        "groups": groups,
        "scale": round(scale_y, 2),
        "vlmImageHeight": vlm_img_h,
        "realImageHeight": img_h,
        "elapsed": elapsed,
        "pageIndex": body.pageIndex,
        "totalAreas": len(areas),
        "assignedAreas": len(assigned),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9020)
