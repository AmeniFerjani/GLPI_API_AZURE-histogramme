# =============================================================
# main.py  —  GLPI Agent API  (version finale complète)
# Azure App Service · Python 3.11 · FastAPI
#
# Endpoints :
#   POST /execute-sql                  → SQL query (toujours HTTP 200)
#   POST /generate-chart               → PNG statique  (image_url)
#   POST /generate-chart-interactive   → HTML Plotly   (interactive_url)
#   POST /generate-excel               → fichier .xlsx en téléchargement
#   GET  /static/<fichier>             → servir les fichiers générés
#   GET  /healthz                      → santé + test DB
# =============================================================

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any
import os, io, uuid, json, base64, tempfile
from datetime import datetime, date

import mysql.connector

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import matplotlib
matplotlib.use("Agg")          # pas de display — obligatoire en server
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ── Dossier statique pour les fichiers générés ───────────────
STATIC_DIR = "/tmp/glpi_static"
os.makedirs(STATIC_DIR, exist_ok=True)

app = FastAPI(title="GLPI Agent API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# =============================================================
# Modèles Pydantic
# =============================================================

class SQLQuery(BaseModel):
    query: str

class ChartRequest(BaseModel):
    data: List[List[Any]]           # [[label, valeur], ...]
    chart_type: str                 # bar | barh | line | area | pie | donut
    title: Optional[str] = "Graphique GLPI"
    x_label: Optional[str] = ""
    y_label: Optional[str] = ""
    color_theme: Optional[str] = "blue"   # blue | green | orange | mixed

class InteractiveChartRequest(BaseModel):
    data: List[List[Any]]
    chart_type: str
    title: Optional[str] = "Graphique GLPI"
    x_label: Optional[str] = ""
    y_label: Optional[str] = ""

class ExcelRequest(BaseModel):
    query: str
    title: Optional[str] = "Rapport GLPI"
    sheet_name: Optional[str] = "Données"
    include_chart: Optional[bool] = False
    chart_type: Optional[str] = "bar"


# =============================================================
# Palettes de couleurs
# =============================================================

PALETTES = {
    "blue":   ["#1F4E79","#2E75B6","#5B9BD5","#9DC3E6","#BDD7EE","#DEEAF1"],
    "green":  ["#375623","#538135","#70AD47","#A9D18E","#C5E0B4","#E2EFDA"],
    "orange": ["#843C0C","#C55A11","#ED7D31","#F4B183","#F8CBAD","#FCE4D6"],
    "mixed":  ["#2E75B6","#70AD47","#ED7D31","#FFC000","#5B9BD5","#A9D18E",
               "#F4B183","#FFE699","#843C0C","#375623","#1F4E79","#806000"],
}


# =============================================================
# Utilitaires DB
# =============================================================

def get_db_conn():
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "197.17.5.110"),
            user=os.getenv("DB_USER", "ameni"),
            password=os.getenv("DB_PASS", "ameni"),
            database=os.getenv("DB_NAME", "ameni"),
            port=int(os.getenv("DB_PORT", "3306")),
            connection_timeout=20,
            charset="utf8mb4",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection error: {e}")


def run_query(query: str):
    """Retourne (colonnes, lignes). Lève HTTPException 400 si erreur SQL."""
    cnx = get_db_conn()
    try:
        cur = cnx.cursor()
        cur.execute(query)
        cols = [d[0] for d in (cur.description or [])]
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


def _safe(v):
    """Sérialise datetime/date/bytes pour JSON."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return None
    return v


def _style_ax(ax, x_label, y_label):
    """Style commun axes bar / line / scatter."""
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", " ")))
    ax.grid(axis="y", linestyle="--", alpha=0.35, color="#CCCCCC")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#DDDDDD")
    ax.spines["bottom"].set_color("#DDDDDD")
    if x_label:
        ax.set_xlabel(x_label, fontsize=9, color="#555")
    if y_label:
        ax.set_ylabel(y_label, fontsize=9, color="#555")


# =============================================================
# POST /execute-sql
# =============================================================

@app.post("/execute-sql")
def execute_sql(payload: SQLQuery):
    """
    Exécute une requête SQL — retourne TOUJOURS HTTP 200.
    En cas d'erreur SQL → {"error": true, "message": "..."}
    En succès scalaire  → {"value": x}
    En succès tableau   → {"columns": [...], "rows": [...]}
    """
    try:
        cols, rows = run_query(payload.query)
    except HTTPException:
        return JSONResponse(status_code=200, content={
            "error": True,
            "message": "Requete invalide ou colonne absente."
        })

    # Résultat scalaire : [[123]]
    if rows and len(rows) == 1 and len(rows[0]) == 1:
        return {"value": _safe(rows[0][0])}

    serialized = [[_safe(c) for c in row] for row in rows]
    return {"columns": cols, "rows": serialized}


# =============================================================
# POST /generate-chart  (PNG statique)
# =============================================================

@app.post("/generate-chart")
def generate_chart(payload: ChartRequest):
    """
    Génère un graphique PNG.
    Retourne image_url  (URL publique /static/chart_xxx.png)
          + image_base64 (fallback si URL inaccessible).

    chart_type : bar | barh | line | area | pie | donut | scatter
    color_theme: blue | green | orange | mixed
    """
    if not payload.data:
        return JSONResponse(status_code=200, content={
            "error": True, "message": "Données vides."})

    labels = [str(r[0]) for r in payload.data]
    values = []
    for r in payload.data:
        try:    values.append(float(r[1]))
        except: values.append(0.0)

    palette = PALETTES.get(payload.color_theme or "blue", PALETTES["blue"])
    colors  = [palette[i % len(palette)] for i in range(len(labels))]
    ctype   = (payload.chart_type or "bar").lower()

    # ── Taille figure selon type ─────────────────────────────
    if ctype in ("pie", "donut"):
        fig, ax = plt.subplots(figsize=(7, 5.5), dpi=140)
    elif ctype == "barh":
        fig_h = max(4, len(labels) * 0.45 + 1.5)
        fig, ax = plt.subplots(figsize=(9, fig_h), dpi=130)
    else:
        fig, ax = plt.subplots(figsize=(11, 5), dpi=130)

    fig.patch.set_facecolor("#FAFAFA")
    ax.set_facecolor("#FAFAFA")

    # ── Rendu selon type ─────────────────────────────────────
    if ctype in ("pie", "donut"):
        w = {"linewidth": 0.8, "edgecolor": "white"}
        if ctype == "donut":
            w["width"] = 0.55
        _, texts, auts = ax.pie(
            values, labels=None, colors=colors,
            autopct="%1.1f%%", startangle=140,
            pctdistance=0.78, wedgeprops=w)
        for a in auts:
            a.set_fontsize(8); a.set_color("white"); a.set_fontweight("bold")
        ax.legend(labels, loc="lower center",
                  bbox_to_anchor=(0.5, -0.12),
                  ncol=min(4, len(labels)), fontsize=8, frameon=False)

    elif ctype in ("line", "area"):
        xi = range(len(labels))
        ax.plot(xi, values, marker="o", color=palette[0],
                linewidth=2.2, markersize=6,
                markerfacecolor="white", markeredgewidth=2, zorder=3)
        if ctype == "area":
            ax.fill_between(xi, values, alpha=0.12, color=palette[0])
        for x, y in zip(xi, values):
            ax.annotate(f"{y:,.0f}".replace(",", " "),
                        xy=(x, y), xytext=(0, 7),
                        textcoords="offset points",
                        ha="center", fontsize=8, color="#444")
        ax.set_xticks(list(xi))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        _style_ax(ax, payload.x_label, payload.y_label)

    elif ctype == "barh":
        yi = range(len(labels))
        bars = ax.barh(yi, values, color=colors,
                       edgecolor="white", linewidth=0.5, height=0.65)
        ax.set_yticks(list(yi))
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.bar_label(bars,
            labels=[f"{v:,.0f}".replace(",", " ") for v in values],
            padding=4, fontsize=8, color="#444")
        ax.xaxis.set_major_formatter(
            mticker.FuncFormatter(lambda x, _: f"{int(x):,}".replace(",", " ")))
        ax.grid(axis="x", linestyle="--", alpha=0.35, color="#CCCCCC")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        if payload.x_label: ax.set_xlabel(payload.x_label, fontsize=9)
        if payload.y_label: ax.set_ylabel(payload.y_label, fontsize=9)

    elif ctype == "scatter":
        ax.scatter(range(len(labels)), values,
                   c=palette[0], s=80, alpha=0.75, zorder=3)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        _style_ax(ax, payload.x_label, payload.y_label)

    else:  # bar (défaut)
        xi = range(len(labels))
        bars = ax.bar(xi, values, color=colors,
                      edgecolor="white", linewidth=0.5, width=0.65)
        ax.bar_label(bars,
            labels=[f"{v:,.0f}".replace(",", " ") for v in values],
            padding=3, fontsize=8, color="#444")
        ax.set_xticks(list(xi))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        _style_ax(ax, payload.x_label, payload.y_label)

    ax.set_title(payload.title, fontsize=13, fontweight="bold",
                 pad=14, color="#1F2D3D")
    plt.tight_layout()

    # ── Sauvegarde PNG statique ───────────────────────────────
    fname = f"chart_{uuid.uuid4().hex[:10]}.png"
    fpath = os.path.join(STATIC_DIR, fname)
    plt.savefig(fpath, format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor())

    # ── Base64 fallback ───────────────────────────────────────
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()

    base_url = os.getenv("APP_BASE_URL", "").rstrip("/")
    image_url = f"{base_url}/static/{fname}" if base_url else f"/static/{fname}"

    return {
        "image_url":    image_url,
        "image_base64": b64,
        "media_type":   "image/png",
        "chart_type":   ctype,
        "nb_points":    len(labels),
    }


# =============================================================
# POST /generate-chart-interactive  (HTML Plotly)
# =============================================================

@app.post("/generate-chart-interactive")
def generate_chart_interactive(payload: InteractiveChartRequest):
    """
    Génère une page HTML Plotly interactive.
    Retourne interactive_url (lien public /static/chart_xxx.html).

    chart_type : bar | barh | line | area | pie | scatter
    """
    if not payload.data:
        return JSONResponse(status_code=200, content={
            "error": True, "message": "Données vides."})

    labels = [str(r[0]) for r in payload.data]
    values = []
    for r in payload.data:
        try:    values.append(float(r[1]))
        except: values.append(0.0)

    ctype  = (payload.chart_type or "bar").lower()
    title  = payload.title or "Graphique GLPI"
    xl     = payload.x_label or ""
    yl     = payload.y_label or ""
    colors = PALETTES["mixed"]

    # ── Trace Plotly selon type ───────────────────────────────
    if ctype == "pie":
        trace = f"""{{
          type:'pie',
          labels:{json.dumps(labels)},
          values:{json.dumps(values)},
          textinfo:'label+percent',
          hovertemplate:'%{{label}}: %{{value:,}}<extra></extra>',
          marker:{{colors:{json.dumps(colors[:len(labels)])}}}
        }}"""
    elif ctype in ("line", "area"):
        fill = "'tozeroy'" if ctype == "area" else "'none'"
        trace = f"""{{
          type:'scatter', mode:'lines+markers',
          x:{json.dumps(labels)}, y:{json.dumps(values)},
          fill:{fill},
          line:{{color:'#2E75B6',width:2.5}},
          marker:{{color:'#1F4E79',size:7}},
          hovertemplate:'%{{x}}: %{{y:,}}<extra></extra>'
        }}"""
    elif ctype in ("barh",):
        bar_colors = (colors * (len(labels)//len(colors)+1))[:len(labels)]
        trace = f"""{{
          type:'bar', orientation:'h',
          x:{json.dumps(values)}, y:{json.dumps(labels)},
          marker:{{color:{json.dumps(bar_colors)}}},
          hovertemplate:'%{{y}}: %{{x:,}}<extra></extra>',
          text:{json.dumps([f"{v:,.0f}".replace(",", " ") for v in values])},
          textposition:'outside'
        }}"""
    elif ctype == "scatter":
        trace = f"""{{
          type:'scatter', mode:'markers',
          x:{json.dumps(labels)}, y:{json.dumps(values)},
          marker:{{color:'#2E75B6',size:9,opacity:0.8}},
          hovertemplate:'%{{x}}: %{{y:,}}<extra></extra>'
        }}"""
    else:  # bar
        bar_colors = (colors * (len(labels)//len(colors)+1))[:len(labels)]
        trace = f"""{{
          type:'bar',
          x:{json.dumps(labels)}, y:{json.dumps(values)},
          marker:{{color:{json.dumps(bar_colors)}}},
          hovertemplate:'%{{x}}: %{{y:,}}<extra></extra>',
          text:{json.dumps([f"{v:,.0f}".replace(",", " ") for v in values])},
          textposition:'outside'
        }}"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Calibri,Arial,sans-serif;background:#F5F7FA;padding:20px}}
h1{{font-size:17px;color:#1F4E79;margin-bottom:14px;text-align:center}}
#chart{{width:100%;height:520px;background:white;border-radius:8px;
        box-shadow:0 1px 6px rgba(0,0,0,.08);padding:10px}}
.meta{{text-align:right;font-size:11px;color:#888;margin-top:8px}}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="chart"></div>
<p class="meta">Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')} — {len(labels)} points</p>
<script>
Plotly.newPlot('chart',[{trace}],{{
  paper_bgcolor:'white', plot_bgcolor:'#F9FAFB',
  margin:{{t:40,b:80,l:70,r:20}},
  xaxis:{{title:{{text:'{xl}',font:{{size:11}}}},tickangle:-35,automargin:true}},
  yaxis:{{title:{{text:'{yl}',font:{{size:11}}}},gridcolor:'#E8ECF0'}},
  font:{{family:'Calibri,Arial',size:12}},hovermode:'closest'
}},{{
  responsive:true,
  modeBarButtonsToRemove:['select2d','lasso2d'],
  toImageButtonOptions:{{format:'png',filename:'graphique_glpi',height:600,width:1100}}
}});
</script>
</body>
</html>"""

    fname = f"chart_interactive_{uuid.uuid4().hex[:10]}.html"
    with open(os.path.join(STATIC_DIR, fname), "w", encoding="utf-8") as f:
        f.write(html)

    base_url = os.getenv("APP_BASE_URL", "").rstrip("/")
    iurl = f"{base_url}/static/{fname}" if base_url else f"/static/{fname}"

    return {
        "interactive_url": iurl,
        "chart_type":      ctype,
        "nb_points":       len(labels),
        "title":           title,
    }


# =============================================================
# POST /generate-excel
# =============================================================

@app.post("/generate-excel")
def generate_excel(payload: ExcelRequest):
    """
    Exécute la requête SQL et retourne un fichier .xlsx téléchargeable.
    Mise en forme : titre coloré, en-têtes, zébrage, auto-width,
    freeze pane, filtres automatiques.
    Option include_chart=true → graphique intégré dans l'Excel.
    """
    try:
        cols, rows = run_query(payload.query)
    except HTTPException as e:
        raise

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (payload.sheet_name or "Données")[:31]

    nb_cols = max(len(cols), 1)

    # ── Styles ───────────────────────────────────────────────
    thin   = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def hfill(hex_color): return PatternFill("solid", fgColor=hex_color)

    # ── Ligne 1 : Titre ──────────────────────────────────────
    ws.merge_cells(start_row=1, start_column=1,
                   end_row=1, end_column=nb_cols)
    tc = ws.cell(row=1, column=1, value=payload.title)
    tc.font      = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    tc.fill      = hfill("1F4E79")
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # ── Ligne 2 : Date + nb enregistrements ──────────────────
    ws.merge_cells(start_row=2, start_column=1,
                   end_row=2, end_column=nb_cols)
    sc = ws.cell(row=2, column=1,
        value=(f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
               f"  —  {len(rows)} enregistrement(s)"))
    sc.font      = Font(name="Calibri", italic=True, size=10, color="595959")
    sc.fill      = hfill("F2F2F2")
    sc.alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[2].height = 16

    # ── Ligne 3 : En-têtes colonnes ──────────────────────────
    for ci, col_name in enumerate(cols, 1):
        cell = ws.cell(row=3, column=ci, value=col_name)
        cell.fill      = hfill("2E75B6")
        cell.font      = Font(name="Calibri", bold=True,
                               color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal="center",
                                    vertical="center", wrap_text=True)
        cell.border    = border
    ws.row_dimensions[3].height = 22

    # ── Données ───────────────────────────────────────────────
    alt_fill  = hfill("EBF3FB")
    norm_font = Font(name="Calibri", size=10)

    for ri, row in enumerate(rows, 4):
        fill = alt_fill if ri % 2 == 0 else None
        for ci, val in enumerate(row, 1):
            cell = ws.cell(row=ri, column=ci)
            if isinstance(val, datetime):
                cell.value = val.strftime("%d/%m/%Y %H:%M")
            elif isinstance(val, date):
                cell.value = val.strftime("%d/%m/%Y")
            elif isinstance(val, (bytes, bytearray)):
                cell.value = None
            else:
                cell.value = val
            cell.font      = norm_font
            cell.border    = border
            cell.alignment = Alignment(vertical="center")
            if fill:
                cell.fill = fill

    # ── Auto-width ────────────────────────────────────────────
    for ci, col_name in enumerate(cols, 1):
        max_len = len(str(col_name))
        for row in rows:
            v = row[ci - 1]
            max_len = max(max_len, len(str(v)) if v is not None else 0)
        ws.column_dimensions[get_column_letter(ci)].width = min(max_len + 4, 55)

    # ── Filtres + freeze ──────────────────────────────────────
    if cols:
        ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A4"

    # ── Graphique intégré (optionnel) ─────────────────────────
    if payload.include_chart and len(cols) >= 2 and len(rows) > 0:
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference, Series
        data_start = 4
        data_end   = 3 + len(rows)
        cat_ref    = Reference(ws, min_col=1,
                               min_row=data_start, max_row=data_end)
        val_ref    = Reference(ws, min_col=2,
                               min_row=data_start, max_row=data_end)

        ct = (payload.chart_type or "bar").lower()
        if ct == "line":
            chart = LineChart()
        elif ct == "pie":
            chart = PieChart()
        else:
            chart = BarChart()
            chart.type     = "col"
            chart.grouping = "clustered"

        chart.title  = payload.title
        chart.style  = 10
        chart.width  = 20
        chart.height = 12

        s = Series(val_ref, title=cols[1] if len(cols) > 1 else "Valeur")
        chart.series.append(s)
        if ct != "pie":
            chart.set_categories(cat_ref)

        ws.add_chart(chart, f"A{data_end + 3}")

    # ── Sauvegarde ────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix=".xlsx", prefix="glpi_", dir=STATIC_DIR)
    wb.save(tmp.name)
    tmp.close()

    filename = f"rapport_glpi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return FileResponse(
        path=tmp.name,
        media_type=("application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"),
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =============================================================
# GET /healthz
# =============================================================

@app.get("/healthz")
def healthz():
    """Vérifie l'état de l'API et de la connexion DB."""
    db_ok = False
    try:
        cnx = get_db_conn()
        cnx.ping(reconnect=False)
        cnx.close()
        db_ok = True
    except Exception:
        pass
    return {
        "status":    "ok" if db_ok else "db_unreachable",
        "db":        "connected" if db_ok else "error",
        "version":   "2.0",
        "timestamp": datetime.now().isoformat(),
    }