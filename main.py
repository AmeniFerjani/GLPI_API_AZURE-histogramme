# main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import mysql.connector
import matplotlib
matplotlib.use("Agg")   # moteur sans interface graphique (obligatoire sur serveur)
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd
import io
import base64
import json
from typing import Optional

app = FastAPI()

# ──────────────────────────────────────────────
# MODÈLES DE DONNÉES
# ──────────────────────────────────────────────

class SQLQuery(BaseModel):
    query: str

class ChartRequest(BaseModel):
    query: str
    chart_type: Optional[str] = "auto"   # auto | bar | line | pie | doughnut | horizontal_bar | area
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
        # Retourne HTTP 200 avec erreur JSON pour que l'agent puisse l'intercepter
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
    """
    Choisit automatiquement le meilleur type de graphique
    selon les données et l'indice fourni par l'agent.
    """
    hint = (hint or "").lower()

    # Indice explicite de l'agent
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

    # Détection automatique selon les données
    if df is None or df.empty:
        return "bar"

    col0 = str(df.iloc[:, 0].dtype)
    n_rows = len(df)

    # Si première colonne contient des mois/années → courbe
    first_vals = df.iloc[:, 0].astype(str).str.lower()
    time_keywords = ["jan", "fev", "mar", "avr", "mai", "juin", "juil",
                     "aou", "sep", "oct", "nov", "dec", "2020", "2021",
                     "2022", "2023", "2024", "2025", "semaine", "q1", "q2", "q3", "q4"]
    if any(any(kw in v for kw in time_keywords) for v in first_vals):
        return "line"

    # Peu de catégories et valeurs en % → pie
    if n_rows <= 6 and df.shape[1] == 2:
        vals = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna()
        if len(vals) > 0 and vals.max() <= 100 and vals.min() >= 0:
            return "pie"

    # Beaucoup de lignes avec labels longs → horizontal_bar
    if n_rows > 8:
        return "horizontal_bar"
    if df.shape[1] >= 2:
        labels = df.iloc[:, 0].astype(str)
        if labels.str.len().mean() > 12:
            return "horizontal_bar"

    return "bar"

# ──────────────────────────────────────────────
# STYLE COMMUN DES GRAPHIQUES
# ──────────────────────────────────────────────

PALETTE = [
    "#3d7fff", "#00d4aa", "#ff6b6b", "#ffc144",
    "#a776ff", "#ff8b42", "#42d3ff", "#ff5b91",
    "#7bff6a", "#ffec42"
]

def apply_dark_style(fig, ax, title, xlabel, ylabel):
    """Applique le style sombre cohérent avec l'interface."""
    BG      = "#0d1220"
    SURFACE = "#111825"
    TEXT    = "#e2e8f8"
    DIM     = "#6b7fa3"
    GRID    = "#1e2740"

    fig.patch.set_facecolor(BG)
    if ax:
        ax.set_facecolor(SURFACE)
        ax.tick_params(colors=DIM, labelsize=9)
        ax.xaxis.label.set_color(DIM)
        ax.yaxis.label.set_color(DIM)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.grid(axis="y", color=GRID, linewidth=0.6, linestyle="--", alpha=0.7)
        ax.set_axisbelow(True)
        if xlabel:
            ax.set_xlabel(xlabel, color=DIM, fontsize=10)
        if ylabel:
            ax.set_ylabel(ylabel, color=DIM, fontsize=10)

    if title:
        fig.suptitle(title, color=TEXT, fontsize=13, fontweight="bold",
                     x=0.05, ha="left", y=0.97)

# ──────────────────────────────────────────────
# GÉNÉRATEURS DE GRAPHIQUES
# ──────────────────────────────────────────────

def make_bar(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0).tolist()
    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(labels, values,
                  color=PALETTE[:len(labels)],
                  edgecolor="#0a0d14", linewidth=0.8,
                  zorder=3)
    # Valeurs au-dessus des barres
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.01,
                f"{val:,.0f}", ha="center", va="bottom",
                color="#e2e8f8", fontsize=9)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    apply_dark_style(fig, ax, title, xlabel, ylabel)
    plt.tight_layout()
    return fig

def make_horizontal_bar(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0).tolist()
    # Trier par valeur décroissante
    pairs = sorted(zip(values, labels), reverse=True)
    values, labels = zip(*pairs) if pairs else ([], [])
    fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.45)))
    bars = ax.barh(labels, values,
                   color=PALETTE[:len(labels)],
                   edgecolor="#0a0d14", linewidth=0.8,
                   zorder=3)
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center",
                color="#e2e8f8", fontsize=9)
    ax.invert_yaxis()
    apply_dark_style(fig, ax, title, xlabel, ylabel)
    ax.grid(axis="x", color="#1e2740", linewidth=0.6, linestyle="--", alpha=0.7)
    ax.grid(axis="y", visible=False)
    plt.tight_layout()
    return fig

def make_line(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, col in enumerate(df.columns[1:]):
        values = pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()
        color = PALETTE[i % len(PALETTE)]
        ax.plot(labels, values, color=color, linewidth=2.2,
                marker="o", markersize=6,
                markerfacecolor="#00d4aa", markeredgecolor="#0a0d14",
                markeredgewidth=1.5, zorder=3, label=col)
        # Remplissage sous la courbe
        ax.fill_between(labels, values, alpha=0.08, color=color)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    if len(df.columns) > 2:
        ax.legend(facecolor="#161c2d", edgecolor="#1e2740",
                  labelcolor="#e2e8f8", fontsize=9)
    apply_dark_style(fig, ax, title, xlabel, ylabel)
    plt.tight_layout()
    return fig

def make_area(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, col in enumerate(df.columns[1:]):
        values = pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()
        color = PALETTE[i % len(PALETTE)]
        ax.fill_between(range(len(labels)), values, alpha=0.35, color=color, zorder=2)
        ax.plot(range(len(labels)), values, color=color, linewidth=2, zorder=3, label=col)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    if len(df.columns) > 2:
        ax.legend(facecolor="#161c2d", edgecolor="#1e2740",
                  labelcolor="#e2e8f8", fontsize=9)
    apply_dark_style(fig, ax, title, xlabel, ylabel)
    plt.tight_layout()
    return fig

def make_pie(df, title, xlabel, ylabel):
    labels = df.iloc[:, 0].astype(str).tolist()
    values = pd.to_numeric(df.iloc[:, 1], errors="coerce").fillna(0).tolist()
    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        colors=PALETTE[:len(labels)],
        autopct="%1.1f%%",
        startangle=140,
        pctdistance=0.75,
        wedgeprops={"edgecolor": "#0a0d14", "linewidth": 2}
    )
    for text in texts:
        text.set_color("#6b7fa3")
        text.set_fontsize(9)
    for autotext in autotexts:
        autotext.set_color("#e2e8f8")
        autotext.set_fontsize(9)
        autotext.set_fontweight("bold")
    # Cercle central pour effet donut
    centre = plt.Circle((0, 0), 0.45, fc="#0d1220")
    ax.add_patch(centre)
    apply_dark_style(fig, None, title, xlabel, ylabel)
    fig.patch.set_facecolor("#0d1220")
    plt.tight_layout()
    return fig

def make_multi_bar(df, title, xlabel, ylabel):
    """Barres groupées pour plusieurs séries."""
    import numpy as np
    labels = df.iloc[:, 0].astype(str).tolist()
    n_groups = len(labels)
    n_series = len(df.columns) - 1
    x = np.arange(n_groups)
    width = 0.7 / n_series
    fig, ax = plt.subplots(figsize=(max(8, n_groups * 0.8), 5))
    for i, col in enumerate(df.columns[1:]):
        values = pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()
        offset = (i - n_series / 2 + 0.5) * width
        ax.bar(x + offset, values, width=width * 0.9,
               color=PALETTE[i % len(PALETTE)],
               label=col, edgecolor="#0a0d14", linewidth=0.6, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.legend(facecolor="#161c2d", edgecolor="#1e2740",
              labelcolor="#e2e8f8", fontsize=9)
    apply_dark_style(fig, ax, title, xlabel, ylabel)
    plt.tight_layout()
    return fig

# ──────────────────────────────────────────────
# CONVERSION FIGURE → PNG BASE64
# ──────────────────────────────────────────────

def fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150,
                bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")

# ──────────────────────────────────────────────
# ENDPOINT ORIGINAL (inchangé)
# ──────────────────────────────────────────────

@app.post("/execute-sql")
def execute_sql(payload: SQLQuery):
    rows, col_names = run_query(payload.query)
    if rows is None:
        # col_names contient le message d'erreur ici
        return JSONResponse(
            status_code=200,
            content={"error": True, "message": str(col_names)}
        )
    if rows and len(rows) == 1 and isinstance(rows[0], (list, tuple)) and len(rows[0]) == 1:
        return {"value": rows[0][0]}
    return {"result": rows}

# ──────────────────────────────────────────────
# ENDPOINT GRAPHIQUE (nouveau)
# ──────────────────────────────────────────────

@app.post("/execute-sql-chart")
def execute_sql_chart(payload: ChartRequest):
    """
    Exécute une requête SQL et retourne :
    - result : les données brutes
    - chart_base64 : l'image PNG encodée en base64
    - chart_html : balise <img> prête à coller dans une page
    - chart_type_used : le type de graphique effectivement généré
    """
    rows, col_names = run_query(payload.query)

    if rows is None:
        return JSONResponse(
            status_code=200,
            content={"error": True, "message": str(col_names)}
        )

    if not rows:
        return JSONResponse(
            status_code=200,
            content={"error": False, "result": [], "chart_base64": None,
                     "message": "Aucune donnée retournée par la requête."}
        )

    # Construire le DataFrame
    try:
        df = pd.DataFrame(rows, columns=col_names)
    except Exception:
        df = pd.DataFrame(rows)

    # Choisir le type de graphique
    chart_type = detect_chart_type(df, payload.chart_type or "auto")

    # Générer le graphique
    try:
        if chart_type == "bar":
            fig = make_bar(df, payload.title, payload.xlabel, payload.ylabel)
        elif chart_type == "horizontal_bar":
            fig = make_horizontal_bar(df, payload.title, payload.xlabel, payload.ylabel)
        elif chart_type == "line":
            fig = make_line(df, payload.title, payload.xlabel, payload.ylabel)
        elif chart_type == "area":
            fig = make_area(df, payload.title, payload.xlabel, payload.ylabel)
        elif chart_type in ("pie", "doughnut"):
            fig = make_pie(df, payload.title, payload.xlabel, payload.ylabel)
        elif chart_type == "multi_bar" or (df.shape[1] > 2):
            fig = make_multi_bar(df, payload.title, payload.xlabel, payload.ylabel)
        else:
            fig = make_bar(df, payload.title, payload.xlabel, payload.ylabel)

        img_b64 = fig_to_base64(fig)
        img_html = (
            f'<img src="data:image/png;base64,{img_b64}" '
            f'style="max-width:100%;border-radius:12px;" />'
        )
    except Exception as e:
        return JSONResponse(
            status_code=200,
            content={"error": True, "message": f"Erreur génération graphique : {str(e)}"}
        )

    return {
        "error": False,
        "result": [list(row) for row in rows],
        "columns": col_names,
        "chart_base64": img_b64,
        "chart_html": img_html,
        "chart_type_used": chart_type,
        "rows_count": len(rows)
    }

# ──────────────────────────────────────────────
# ENDPOINT SANTÉ
# ──────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok"}