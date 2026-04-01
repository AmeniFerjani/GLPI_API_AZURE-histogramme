# main.py — GLPI Agent API compatible Azure AI Foundry
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel
from typing import Optional, List, Any

import os
import uuid
import mysql.connector
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import plotly.express as px
from datetime import datetime


# --------------------------------------------------------------------
# FASTAPI INIT
# --------------------------------------------------------------------
app = FastAPI(title="GLPI Agent API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------
# CREATE PUBLIC STATIC DIRECTORY
# --------------------------------------------------------------------
PUBLIC_DIR = "/home/site/wwwroot/files"
os.makedirs(PUBLIC_DIR, exist_ok=True)

# Public URL exposure
app.mount("/files", StaticFiles(directory=PUBLIC_DIR), name="files")


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
# SQL EXECUTOR — for Foundry
# --------------------------------------------------------------------
@app.post("/execute-sql")
def execute_sql(payload: SQLQuery):
    try:
        cols, rows = run_query(payload.query)
    except:
        return {"error": True, "message": "Requete invalide ou colonne absente."}

    if rows and len(rows) == 1 and len(rows[0]) == 1:
        return {"value": rows[0][0]}

    def safe(v):
        return v.isoformat() if isinstance(v, datetime) else v

    rows = [[safe(x) for x in r] for r in rows]
    return {"columns": cols, "rows": rows}


# --------------------------------------------------------------------
# EXCEL EXPORT — PUBLIC FILE (Foundry download button)
# --------------------------------------------------------------------
@app.post("/generate-excel")
def generate_excel(payload: ExcelRequest):

    cols, rows = run_query(payload.query)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = payload.sheet_name[:31]

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cols))
    c = ws.cell(row=1, column=1, value=payload.title)
    c.font = Font(bold=True, size=14, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="1F4E79")
    c.alignment = Alignment(horizontal="center")

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(cols))
    d = ws.cell(row=2, column=1, value=f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    d.font = Font(italic=True, size=10)
    d.alignment = Alignment(horizontal="right")

    header_fill = PatternFill("solid", fgColor="2E75B6")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for i, name in enumerate(cols, start=1):
        cell = ws.cell(row=3, column=i, value=name)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = border

    for r_index, r in enumerate(rows, start=4):
        for c_index, v in enumerate(r, start=1):
            cell = ws.cell(row=r_index, column=c_index, value=str(v))
            cell.border = border

    filename = f"excel_{uuid.uuid4()}.xlsx"
    filepath = os.path.join(PUBLIC_DIR, filename)
    wb.save(filepath)

    public_url = f"https://{os.getenv('WEBSITE_HOSTNAME')}/files/{filename}"

    return {
        "file_url": public_url,
        "file_name": filename,
        "message": "Excel généré avec succès."
    }


# --------------------------------------------------------------------
# CHART GENERATOR — INTERACTIVE HTML (Foundry-compatible)
# --------------------------------------------------------------------
@app.post("/generate-chart")
def generate_chart(payload: ChartRequest):

    if not payload.data:
        raise HTTPException(status_code=400, detail="data vide")

    labels = [str(x[0]) for x in payload.data]
    values = [float(x[1]) if x[1] else 0 for x in payload.data]

    # Interactive Plotly Chart
    if payload.chart_type == "pie":
        fig = px.pie(names=labels, values=values, title=payload.title)
    elif payload.chart_type == "line":
        fig = px.line(x=labels, y=values, title=payload.title)
    else:
        fig = px.bar(x=labels, y=values, title=payload.title)

    filename = f"chart_{uuid.uuid4()}.html"
    filepath = os.path.join(PUBLIC_DIR, filename)

    fig.write_html(filepath)

    public_url = f"https://{os.getenv('WEBSITE_HOSTNAME')}/files/{filename}"

    return {
        "image_url": public_url,
        "chart_type": payload.chart_type,
        "message": "Graphique généré."
    }


# --------------------------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "version": "4.0",
        "timestamp": datetime.now().isoformat()
    }