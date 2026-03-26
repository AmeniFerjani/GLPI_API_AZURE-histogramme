from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import uuid
import mysql.connector
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import io
import base64
from typing import Optional
from pathlib import Path

app = FastAPI()

# ──────────────────────────────────────────────
# DOSSIER STATIQUE PERSISTANT
# /home/site/wwwroot est persistant sur Azure App Service Linux
# /tmp est effacé à chaque redémarrage — ne pas utiliser
# ──────────────────────────────────────────────

CHARTS_DIR = Path("/home/site/wwwroot/charts")
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/charts", StaticFiles(directory=str(CHARTS_DIR)), name="charts")

APP_BASE_URL = os.getenv(
    "APP_BASE_URL",
    "https://appservicegentixhistogramme-btevcsfpbxhqard7.eastus-01.azurewebsites.net"
).rstrip("/")

# ──────────────────────────────────────────────
# MODÈLES DE DONNÉES
# ──────────────────────────────────────────────

class SQLQuery(BaseModel):
    query: str

class ChartRequest(BaseModel):
    query: str
    chart_type: Optional[str] = "auto"
    title: Optional[str] = ""
    xlabel: Optional[str] = ""
    ylabel: Optional[str] = ""

# ──────────────────────────────────────────────
# CONNEXION BASE DE DONNÉES
# ──────────────────────────────────────────────

def get_db_conn():
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "197.17.5.110"),
            user=os.getenv("DB_USER", "ameni"),
            password=os.getenv("DB_PASS", "ameni"),
            database=os.getenv("DB_NAME", "ameni"),
            port=int(os.getenv("DB_PORT", "3306")),
            connection_timeout=10
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection error: {e}")

def run_query(query: str):
    cnx = get_db_conn()
    try:
        cur = cnx.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description] if cur.description else []
        return rows, col_names
    except Exception as e:
        return None, str(e)
    finally:
        try:
            cur.close()
        except:
            pass
        cnx.close()

# ──────────────────────────────────────────────
# DÉTECTION AUTOMATIQUE DU TYPE DE GRAPHIQUE
# ──────────────────────────────────────────────

def detect_chart_type(df: pd.DataFrame, hint: str) -> str:
    hint = (hint or "").lower()
    if "line" in hint or "courbe" in hint or "evolution" in hint or "tendance" in hint:
        return "line"
    if "pie" in hint or "camembert" in hint or "donut" in hint or "doughnut" in hint:
        return "pie"
    if "horizontal" in hint or "classement" in hint or "top" in hint:
        return "horizontal_bar"
    if "area" in hint or "aire" in hint:
        return "area"
    if "bar" in hint or "histogramme" in hint or "colonne" in hint:
        return "bar"
    if df is None or df.empty:
        return "bar"
    n_rows = len(df)
    first_vals = df.iloc[:, 0].astype(str).str.lower()
    time_keywords = ["jan","fev","mar","avr","mai","juin","juil","aou","sep","oct","nov","dec",
                     "2020","2021","2022","2023","2024","2025","semaine","q1","q2","q3","q4"]
    if any(any(kw in v for kw in time_keywords) for v in first_vals):
        return "line"
    if n_rows <= 6 and df.shape[1] == 2:
        vals = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna()
        if len(vals) > 0 and vals.max() <= 100 and vals.min() >= 0:
            return "pie"
    if n_rows > 8:
        return "horizontal_bar"
    if df.shape[1] >= 2 and df.iloc[:, 0].astype(str).str.len().mean() > 12:
        return "horizontal_bar"
    return "bar"

# ──────────────────────────────────────────────
# STYLE GRAPHIQUES
# ──────────────────────────────────────────────

PALETTE = ["#3d7fff","#00d4aa","#ff6b6b","#ffc144","#a776ff",
           "#ff8b42","#42d3ff","#ff5b91","#7bff6a","#ffec42"]

def apply_dark_style(fig, ax, title, xlabel, ylabel):
    BG="#0d1220"; SURFACE="#111825"; TEXT="#e2e8f8"; DIM="#6b7fa3"; GRID="#1e2740"
    fig.patch.set_facecolor(BG)
    if ax:
        ax.set_facecolor(SURFACE)
        ax.tick_params(colors=DIM, labelsize=9)
        ax.xaxis.label.set_color(DIM); ax.yaxis.label.set_color(DIM)
        for spine in ax.spines.values(): spine.set_edgecolor(GRID)
        ax.grid(axis="y", color=GRID, linewidth=0.6, linestyle="--", alpha=0.7)
        ax.set_axisbelow(True)
        if xlabel: ax.set_xlabel(xlabel, color=DIM, fontsize=10)
        if ylabel: ax.set_ylabel(ylabel, color=DIM, fontsize=10)
    if title:
        fig.suptitle(title, color=TEXT, fontsize=13, fontweight="bold", x=0.05, ha="left", y=0.97)

# ──────────────────────────────────────────────
# GÉNÉRATEURS
# ──────────────────────────────────────────────

def make_bar(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0).tolist()
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(labels, values, color=PALETTE[:len(labels)], edgecolor="#0a0d14", linewidth=0.8, zorder=3)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+max(values)*0.01,
                f"{val:,.0f}", ha="center", va="bottom", color="#e2e8f8", fontsize=9)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=30, ha="right")
    apply_dark_style(fig, ax, title, xlabel, ylabel); plt.tight_layout(); return fig

def make_horizontal_bar(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0).tolist()
    pairs = sorted(zip(values, labels), reverse=True)
    values, labels = zip(*pairs) if pairs else ([], [])
    fig, ax = plt.subplots(figsize=(10, max(4, len(labels)*0.45)))
    bars = ax.barh(labels, values, color=PALETTE[:len(labels)], edgecolor="#0a0d14", linewidth=0.8, zorder=3)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width()+max(values)*0.01, bar.get_y()+bar.get_height()/2,
                f"{val:,.0f}", va="center", color="#e2e8f8", fontsize=9)
    ax.invert_yaxis(); apply_dark_style(fig, ax, title, xlabel, ylabel)
    ax.grid(axis="x", color="#1e2740", linewidth=0.6, linestyle="--", alpha=0.7)
    ax.grid(axis="y", visible=False); plt.tight_layout(); return fig

def make_line(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, col in enumerate(df.columns[1:]):
        values = pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()
        color = PALETTE[i % len(PALETTE)]
        ax.plot(labels, values, color=color, linewidth=2.2, marker="o", markersize=6,
                markerfacecolor="#00d4aa", markeredgecolor="#0a0d14", markeredgewidth=1.5, zorder=3, label=col)
        ax.fill_between(labels, values, alpha=0.08, color=color)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=30, ha="right")
    if len(df.columns) > 2:
        ax.legend(facecolor="#161c2d", edgecolor="#1e2740", labelcolor="#e2e8f8", fontsize=9)
    apply_dark_style(fig, ax, title, xlabel, ylabel); plt.tight_layout(); return fig

def make_area(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, col in enumerate(df.columns[1:]):
        values = pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()
        color = PALETTE[i % len(PALETTE)]
        ax.fill_between(range(len(labels)), values, alpha=0.35, color=color, zorder=2)
        ax.plot(range(len(labels)), values, color=color, linewidth=2, zorder=3, label=col)
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=30, ha="right")
    if len(df.columns) > 2:
        ax.legend(facecolor="#161c2d", edgecolor="#1e2740", labelcolor="#e2e8f8", fontsize=9)
    apply_dark_style(fig, ax, title, xlabel, ylabel); plt.tight_layout(); return fig

def make_pie(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0).tolist()
    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, colors=PALETTE[:len(labels)],
        autopct="%1.1f%%", startangle=140, pctdistance=0.75,
        wedgeprops={"edgecolor": "#0a0d14", "linewidth": 2})
    for t in texts: t.set_color("#6b7fa3"); t.set_fontsize(9)
    for at in autotexts: at.set_color("#e2e8f8"); at.set_fontsize(9); at.set_fontweight("bold")
    ax.add_patch(plt.Circle((0,0), 0.45, fc="#0d1220"))
    apply_dark_style(fig, None, title, xlabel, ylabel)
    fig.patch.set_facecolor("#0d1220"); plt.tight_layout(); return fig

def make_multi_bar(df, title, xlabel, ylabel):
    import numpy as np
    labels = df.iloc[:, 0].astype(str).tolist()
    n_series = len(df.columns) - 1
    x = np.arange(len(labels)); width = 0.7 / n_series
    fig, ax = plt.subplots(figsize=(max(8, len(labels)*0.8), 5))
    for i, col in enumerate(df.columns[1:]):
        values = pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()
        ax.bar(x+(i-n_series/2+0.5)*width, values, width=width*0.9,
               color=PALETTE[i%len(PALETTE)], label=col, edgecolor="#0a0d14", linewidth=0.6, zorder=3)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.legend(facecolor="#161c2d", edgecolor="#1e2740", labelcolor="#e2e8f8", fontsize=9)
    apply_dark_style(fig, ax, title, xlabel, ylabel); plt.tight_layout(); return fig

# ──────────────────────────────────────────────
# SAUVEGARDE PERSISTANTE + GÉNÉRATION URL
# ──────────────────────────────────────────────

def fig_to_files(fig, title: str) -> dict:
    filename = f"{uuid.uuid4().hex}.png"
    filepath = CHARTS_DIR / filename

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()

    with open(filepath, "wb") as f:
        f.write(png_bytes)

    safe_title = (title or "Graphique").replace('"', '').replace("'", "")
    view_url   = f"{APP_BASE_URL}/chart-view/{filename}"
    chart_url  = f"{APP_BASE_URL}/charts/{filename}"

    return {
        "view_url":  view_url,
        "chart_url": chart_url,
        "filename":  filename,
        # Texte exact que l'agent doit copier dans sa réponse
        "agent_response": f"Voici le graphique : [{safe_title}]({view_url})",
    }

# ──────────────────────────────────────────────
# ENDPOINT : PAGE HTML D'AFFICHAGE
# ──────────────────────────────────────────────

@app.get("/chart-view/{filename}", response_class=HTMLResponse)
def chart_view(filename: str):
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    chart_url = f"{APP_BASE_URL}/charts/{filename}"
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Graphique GLPI</title>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{background:#0d1220;display:flex;align-items:center;
          justify-content:center;min-height:100vh;
          font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
    .card{{background:#111825;border-radius:16px;padding:28px;max-width:95vw;
           box-shadow:0 8px 32px rgba(0,0,0,.5)}}
    .header{{color:#6b7fa3;font-size:12px;margin-bottom:14px;text-align:center;
             letter-spacing:.05em;text-transform:uppercase}}
    img{{max-width:100%;border-radius:8px;display:block}}
    .dl{{display:block;text-align:center;margin-top:14px;color:#3d7fff;
         font-size:13px;text-decoration:none}}
    .dl:hover{{text-decoration:underline}}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">Graphique GLPI — Agent Analytique</div>
    <img src="{chart_url}" alt="Graphique GLPI">
    <a class="dl" href="{chart_url}" download>Telecharger l'image</a>
  </div>
</body>
</html>""")

# ──────────────────────────────────────────────
# ENDPOINT SQL SIMPLE
# ──────────────────────────────────────────────

@app.post("/execute-sql")
def execute_sql(payload: SQLQuery):
    rows, col_names = run_query(payload.query)
    if rows is None:
        return JSONResponse(status_code=200, content={"error": True, "message": str(col_names)})
    if rows and len(rows) == 1 and isinstance(rows[0], (list, tuple)) and len(rows[0]) == 1:
        return {"value": rows[0][0]}
    return {"result": rows}

# ──────────────────────────────────────────────
# ENDPOINT GRAPHIQUE
# ──────────────────────────────────────────────

@app.post("/execute-sql-chart")
def execute_sql_chart(payload: ChartRequest):
    rows, col_names = run_query(payload.query)

    if rows is None:
        return JSONResponse(status_code=200, content={"error": True, "message": str(col_names)})

    if not rows:
        return JSONResponse(status_code=200, content={
            "error": False, "result": [],
            "agent_response": "Aucune donnee retournee par la requete.",
        })

    try:
        df = pd.DataFrame(rows, columns=col_names)
    except Exception:
        df = pd.DataFrame(rows)

    chart_type = detect_chart_type(df, payload.chart_type or "auto")

    try:
        makers = {
            "bar":            make_bar,
            "horizontal_bar": make_horizontal_bar,
            "line":           make_line,
            "area":           make_area,
            "pie":            make_pie,
            "doughnut":       make_pie,
        }
        maker = makers.get(chart_type, make_bar if df.shape[1] <= 2 else make_multi_bar)
        fig = maker(df, payload.title, payload.xlabel, payload.ylabel)
        files = fig_to_files(fig, payload.title)
    except Exception as e:
        return JSONResponse(status_code=200, content={"error": True, "message": f"Erreur generation : {str(e)}"})

    return {
        "error":           False,
        "rows_count":      len(rows),
        "chart_type_used": chart_type,
        # ↓ L'agent copie ce texte mot pour mot dans sa réponse
        "agent_response":  files["agent_response"],
        "view_url":        files["view_url"],
        "chart_url":       files["chart_url"],
    }

# ──────────────────────────────────────────────
# SANTÉ
# ──────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok"}