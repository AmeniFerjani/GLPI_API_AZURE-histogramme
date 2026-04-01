# main.py — GLPI Agent API compatible Azure AI Foundry
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any
import os, uuid, io, base64, tempfile
import mysql.connector
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime

# --------------------------------------------------------------------
# FASTAPI INIT
# --------------------------------------------------------------------
app = FastAPI(title="GLPI Agent API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------
# MODELS
# --------------------------------------------------------------------
class SQLQuery(BaseModel):
    query: str

class ExcelRequest(BaseModel):
    query: str
    title: Optional[str] = "Rapport GLPI"
    sheet_name: Optional[str] = "Rapport"

class ChartRequest(BaseModel):
    data: List[List[Any]]
    chart_type: str              # "bar" | "line" | "pie"
    title: Optional[str] = "Graphique GLPI"
    x_label: Optional[str] = ""
    y_label: Optional[str] = ""

# --------------------------------------------------------------------
# DATABASE
# --------------------------------------------------------------------
def get_db_conn():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "197.17.5.110"),
        user=os.getenv("DB_USER", "ameni"),
        password=os.getenv("DB_PASS", "ameni"),
        database=os.getenv("DB_NAME", "ameni"),
        port=int(os.getenv("DB_PORT", "3306")),
        connection_timeout=10,
        charset="utf8mb4"
    )

def run_query(sql: str):
    db = get_db_conn()
    try:
        cur = db.cursor()
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        return cols, rows
    except:
        raise HTTPException(status_code=400, detail="SQL error")
    finally:
        cur.close()
        db.close()

# --------------------------------------------------------------------
# SQL EXECUTOR — COMPATIBLE FOUNDRY
# --------------------------------------------------------------------
@app.post("/execute-sql")
def execute_sql(payload: SQLQuery):

    try:
        cols, rows = run_query(payload.query)
    except:
        return {"error": True, "message": "Requete invalide ou colonne absente."}

    if rows and len(rows) == 1 and len(rows[0]) == 1:
        return {"value": rows[0][0]}

    # safe serialization
    def safe(v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    rows = [[safe(x) for x in r] for r in rows]
    return {"columns": cols, "rows": rows}

# --------------------------------------------------------------------
# EXCEL EXPORT — COMPATIBLE FOUNDRY (file_url)
# --------------------------------------------------------------------
@app.post("/generate-excel")
def generate_excel(payload: ExcelRequest):

    cols, rows = run_query(payload.query)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = payload.sheet_name[:31]

    # Title
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    c = ws.cell(row=1, column=1, value=payload.title)
    c.font = Font(bold=True, size=14, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="1F4E79")
    c.alignment = Alignment(horizontal="center")

    # Date
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(cols))
    d = ws.cell(row=2, column=1, value=f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    d.font = Font(italic=True, size=10)
    d.alignment = Alignment(horizontal="right")

    # Header
    header_fill = PatternFill("solid", fgColor="2E75B6")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for i, name in enumerate(cols, start=1):
        cell = ws.cell(row=3, column=i, value=name)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    # Rows
    for r_index, r in enumerate(rows, start=4):
        for c_index, v in enumerate(r, start=1):
            cell = ws.cell(row=r_index, column=c_index, value=str(v))
            cell.border = border

    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A4"

    # Temp file
    tmp_path = f"/tmp/{uuid.uuid4()}.xlsx"
    wb.save(tmp_path)

    return {
        "file_url": tmp_path,
        "file_name": "rapport_glpi.xlsx",
        "message": "Excel généré avec succès."
    }

# --------------------------------------------------------------------
# CHART GENERATOR — COMPATIBLE FOUNDRY (image_url)
# --------------------------------------------------------------------
@app.post("/generate-chart")
def generate_chart(payload: ChartRequest):

    if not payload.data:
        raise HTTPException(status_code=400, detail="data vide")

    labels = [str(x[0]) for x in payload.data]
    values = [float(x[1]) if x[1] else 0 for x in payload.data]

    fig, ax = plt.subplots(figsize=(10, 4), dpi=120)

    if payload.chart_type == "pie":
        ax.pie(values, labels=labels, autopct="%1.1f%%")
    elif payload.chart_type == "line":
        ax.plot(labels, values)
    else:
        ax.bar(labels, values)

    ax.set_title(payload.title)

    tmp_path = f"/tmp/{uuid.uuid4()}.png"
    plt.savefig(tmp_path, bbox_inches="tight")
    plt.close()

    return {
        "image_url": tmp_path,
        "chart_type": payload.chart_type,
        "message": "Graphique généré."
    }

# --------------------------------------------------------------------
# HEALTHZ
# --------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "version": "3.0",
        "timestamp": datetime.now().isoformat()
    }
