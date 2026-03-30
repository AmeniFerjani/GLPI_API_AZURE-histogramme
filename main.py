# main.py — GLPI Agent API
# Azure App Service Python 3.11
# Endpoints: /execute-sql  /generate-excel  /generate-chart  /healthz

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any
import os
import mysql.connector
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import matplotlib
matplotlib.use("Agg")          # backend sans display
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import io, base64, uuid, tempfile, json
from datetime import datetime

app = FastAPI(title="GLPI Agent API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Modèles Pydantic
# ─────────────────────────────────────────────────────────────

class SQLQuery(BaseModel):
    query: str

class ExcelRequest(BaseModel):
    query: str
    title: Optional[str] = "Rapport GLPI"
    sheet_name: Optional[str] = "Données"

class ChartRequest(BaseModel):
    data: List[List[Any]]          # [[label, valeur], ...]
    chart_type: str                # "bar" | "line" | "pie"
    title: Optional[str] = "Graphique GLPI"
    x_label: Optional[str] = ""
    y_label: Optional[str] = ""

# ─────────────────────────────────────────────────────────────
# Connexion DB
# ─────────────────────────────────────────────────────────────

def get_db_conn():
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "197.17.5.110"),
            user=os.getenv("DB_USER", "ameni"),
            password=os.getenv("DB_PASS", "ameni"),
            database=os.getenv("DB_NAME", "ameni"),
            port=int(os.getenv("DB_PORT", "3306")),
            connection_timeout=15,
            charset="utf8mb4",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection error: {e}")

def run_query(query: str):
    """Exécute une requête SELECT et retourne (colonnes, lignes)."""
    cnx = get_db_conn()
    try:
        cur = cnx.cursor()
        cur.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return cols, rows
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL error: {e}")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        cnx.close()

# ─────────────────────────────────────────────────────────────
# /execute-sql  (compatibilité agent Foundry)
# ─────────────────────────────────────────────────────────────

@app.post("/execute-sql")
def execute_sql(payload: SQLQuery):
    """
    Retourne TOUJOURS HTTP 200.
    En cas d'erreur SQL → {"error": true, "message": "..."}
    En cas de succès   → {"value": x} ou {"columns": [...], "rows": [...]}
    """
    try:
        cols, rows = run_query(payload.query)
    except HTTPException as e:
        # Masquer l'erreur brute pour l'agent (règle prompt)
        return JSONResponse(
            status_code=200,
            content={"error": True, "message": "Requete invalide ou colonne absente."}
        )

    # Résultat scalaire : [[123]]
    if rows and len(rows) == 1 and len(rows[0]) == 1:
        return {"value": rows[0][0]}

    # Sérialisation safe (datetime → str)
    def safe(v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    serialized = [[safe(c) for c in row] for row in rows]
    return {"columns": cols, "rows": serialized}

# ─────────────────────────────────────────────────────────────
# /generate-excel  — export .xlsx
# ─────────────────────────────────────────────────────────────

@app.post("/generate-excel")
def generate_excel(payload: ExcelRequest):
    """
    Exécute la requête SQL et retourne un fichier Excel (.xlsx)
    mis en forme avec en-tête coloré, filtres et auto-width.
    """
    try:
        cols, rows = run_query(payload.query)
    except HTTPException as e:
        raise

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = payload.sheet_name[:31]  # Excel limite à 31 chars

    # ── Titre du rapport ──
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(cols), 1))
    title_cell = ws.cell(row=1, column=1, value=payload.title)
    title_cell.font = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor="1F4E79")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # ── Date de génération ──
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(len(cols), 1))
    date_cell = ws.cell(row=2, column=1, value=f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    date_cell.font = Font(name="Calibri", italic=True, size=10, color="595959")
    date_cell.alignment = Alignment(horizontal="right")
    ws.row_dimensions[2].height = 16

    # ── En-têtes colonnes ──
    header_fill = PatternFill("solid", fgColor="2E75B6")
    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col_idx, col_name in enumerate(cols, start=1):
        cell = ws.cell(row=3, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    ws.row_dimensions[3].height = 20

    # ── Données ──
    alt_fill = PatternFill("solid", fgColor="EBF3FB")
    normal_font = Font(name="Calibri", size=10)

    for row_idx, row in enumerate(rows, start=4):
        fill = alt_fill if row_idx % 2 == 0 else None
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            # Conversion datetime
            if hasattr(value, "isoformat"):
                cell.value = value.strftime("%d/%m/%Y %H:%M") if hasattr(value, "hour") else str(value)
            else:
                cell.value = value
            cell.font = normal_font
            cell.border = border
            cell.alignment = Alignment(vertical="center")
            if fill:
                cell.fill = fill

    # ── Auto-width ──
    for col_idx, col_name in enumerate(cols, start=1):
        max_len = len(str(col_name))
        for row in rows:
            val = row[col_idx - 1]
            max_len = max(max_len, len(str(val)) if val is not None else 0)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 50)

    # ── Filtres automatiques ──
    if cols:
        ws.auto_filter.ref = ws.dimensions

    # ── Pane freeze (fige l'en-tête) ──
    ws.freeze_panes = "A4"

    # Sauvegarde dans un fichier temporaire
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", prefix="glpi_")
    wb.save(tmp.name)
    tmp.close()

    filename = f"glpi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return FileResponse(
        path=tmp.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# ─────────────────────────────────────────────────────────────
# /generate-chart  — graphique en base64 PNG
# ─────────────────────────────────────────────────────────────

CHART_COLORS = [
    "#2E75B6", "#70AD47", "#ED7D31", "#FFC000",
    "#5B9BD5", "#A9D18E", "#F4B183", "#FFE699",
    "#44546A", "#375623",
]

@app.post("/generate-chart")
def generate_chart(payload: ChartRequest):
    """
    Retourne un graphique encodé en base64 PNG.
    data = [[label, valeur], ...]
    chart_type = "bar" | "line" | "pie"
    """
    if not payload.data:
        raise HTTPException(status_code=400, detail="data est vide")

    labels = [str(row[0]) for row in payload.data]
    values = []
    for row in payload.data:
        try:
            values.append(float(row[1]))
        except (ValueError, TypeError, IndexError):
            values.append(0.0)

    fig, ax = plt.subplots(figsize=(10, 5), dpi=130)
    fig.patch.set_facecolor("#F9F9F9")
    ax.set_facecolor("#F9F9F9")

    ctype = payload.chart_type.lower()

    if ctype == "pie":
        wedge_colors = CHART_COLORS[:len(labels)]
        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=wedge_colors,
            autopct="%1.1f%%",
            startangle=140,
            pctdistance=0.8,
            wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
        )
        for at in autotexts:
            at.set_fontsize(8)
    elif ctype == "line":
        ax.plot(labels, values, marker="o", color=CHART_COLORS[0],
                linewidth=2, markersize=6, markerfacecolor="white",
                markeredgewidth=2)
        ax.fill_between(range(len(labels)), values, alpha=0.08, color=CHART_COLORS[0])
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{int(x):,}".replace(",", " ")))
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if payload.x_label:
            ax.set_xlabel(payload.x_label, fontsize=9)
        if payload.y_label:
            ax.set_ylabel(payload.y_label, fontsize=9)
    else:  # bar (défaut)
        bar_colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(labels))]
        bars = ax.bar(labels, values, color=bar_colors, edgecolor="white",
                      linewidth=0.6, width=0.65)
        ax.bar_label(bars,
                     labels=[f"{int(v):,}".replace(",", " ") for v in values],
                     padding=3, fontsize=8, color="#444")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{int(x):,}".replace(",", " ")))
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if payload.x_label:
            ax.set_xlabel(payload.x_label, fontsize=9)
        if payload.y_label:
            ax.set_ylabel(payload.y_label, fontsize=9)

    ax.set_title(payload.title, fontsize=13, fontweight="bold", pad=14, color="#1F2D3D")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode()

    return {
        "image_base64": img_b64,
        "media_type": "image/png",
        "chart_type": ctype,
        "nb_points": len(labels),
    }

# ─────────────────────────────────────────────────────────────
# /healthz
# ─────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": "2.0", "timestamp": datetime.now().isoformat()}