"""Ticket Debugger - FastAPI Backend Server (Upload-based)"""

import json
import shutil
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Ticket Debugger")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/upload")
async def upload_ticket(files: List[UploadFile] = File(...)):
    """Upload a ticket folder (multiple files with relative paths)."""
    if not files:
        raise HTTPException(400, "No files uploaded")

    ticket_id = None
    saved_files = []

    for f in files:
        # Browser sends webkitRelativePath as filename: "ticketId/file.jpg"
        rel_path = f.filename.replace("\\", "/")
        parts = rel_path.split("/")

        # First directory is the ticket folder name
        if ticket_id is None:
            ticket_id = parts[0]

        # Save file preserving subdirectory structure
        dest = UPLOAD_DIR / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await f.read()
        dest.write_bytes(content)
        saved_files.append(rel_path)

    return {"ticketId": ticket_id, "fileCount": len(saved_files)}


@app.delete("/api/tickets/{ticket_id}")
async def delete_ticket(ticket_id: str):
    """Delete an uploaded ticket."""
    ticket_dir = UPLOAD_DIR / ticket_id
    if not ticket_dir.exists():
        raise HTTPException(404, "Ticket not found")
    shutil.rmtree(ticket_dir)
    return {"deleted": ticket_id}


@app.get("/api/tickets")
async def list_tickets():
    """List all uploaded ticket IDs."""
    if not UPLOAD_DIR.exists():
        return []
    tickets = sorted(
        [d.name for d in UPLOAD_DIR.iterdir() if d.is_dir()],
        reverse=True,
    )
    results = []
    for tid in tickets:
        config_path = UPLOAD_DIR / tid / "config.json"
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
async def get_ticket(ticket_id: str):
    """Get full ticket config."""
    config_path = UPLOAD_DIR / ticket_id / "config.json"
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

    # Extract table data from top-level integrator
    integrator = data.get("integrator", {})
    tables = []
    for tbl in integrator.get("tableList", []):
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
                }
            rows.append(row)
        tables.append({
            "table": tbl.get("table"),
            "name": tbl.get("name"),
            "type": tbl.get("type"),
            "headers": headers,
            "rows": rows,
        })
    summary["tables"] = tables

    # Extract regList page info (lightweight)
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
async def get_page_areas(ticket_id: str, page_index: int):
    """Get analyzer areaList for a specific page."""
    config_path = UPLOAD_DIR / ticket_id / "config.json"
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
async def get_image(ticket_id: str, filename: str):
    """Serve ticket images."""
    file_path = UPLOAD_DIR / ticket_id / filename
    if not file_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(file_path, media_type="image/jpeg")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9020)
