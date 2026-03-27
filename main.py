# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import mysql.connector

# --- Génération graphiques PNG ---
import matplotlib.pyplot as plt
import pandas as pd
import uuid

# --- Graphe interactif Plotly ---
import plotly.graph_objects as go

# Fichiers statiques
from fastapi.staticfiles import StaticFiles

app = FastAPI()


# ---------------------------------------------------------
#  PARTIE 1 — API SQL (inchangée)
# ---------------------------------------------------------

class SQLQuery(BaseModel):
    query: str


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
        return rows
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL error: {e}")
    finally:
        try:
            cur.close()
        except:
            pass
        cnx.close()


@app.post("/execute-sql")
def execute_sql(payload: SQLQuery):
    rows = run_query(payload.query)
    if rows and len(rows) == 1 and isinstance(rows[0], (list, tuple)) and len(rows[0]) == 1:
        return {"value": rows[0][0]}
    return {"result": rows}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------
#  PARTIE 2 — FICHIERS STATIQUES POUR IMAGES & HTML
# ---------------------------------------------------------

# Créer dossier "static" si inexistant
if not os.path.exists("static"):
    os.makedirs("static")

# Monter /static accessible publiquement
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------
#  PARTIE 3 — FORMAT JSON pour graphiques
# ---------------------------------------------------------

class ChartRequest(BaseModel):
    labels: list
    values: list
    chart_type: str   # "bar", "line", "pie"
    title: str = ""


# ---------------------------------------------------------
#  PARTIE 4 — GRAPHIQUE PNG (Matplotlib)
# ---------------------------------------------------------

@app.post("/generate-chart")
def generate_chart(payload: ChartRequest):

    df = pd.DataFrame({
        "labels": payload.labels,
        "values": payload.values
    })

    fig, ax = plt.subplots(figsize=(7, 4))

    chart = payload.chart_type.lower()

    try:
        if chart == "bar":
            ax.bar(df["labels"], df["values"])
        elif chart == "line":
            ax.plot(df["labels"], df["values"], marker="o")
        elif chart == "pie":
            ax.pie(df["values"], labels=df["labels"], autopct='%1.1f%%')
        else:
            return {"error": "unsupported chart type"}
    except Exception as e:
        return {"error": f"chart generation error: {e}"}

    ax.set_title(payload.title)
    plt.tight_layout()

    # Nom unique
    file_id = uuid.uuid4()
    filename = f"chart_{file_id}.png"
    filepath = os.path.join("static", filename)

    try:
        fig.savefig(filepath, format="png")
    except Exception as e:
        return {"error": f"file saving error: {e}"}

    # ⚠️ IMPORTANT : Mets ici l’URL réelle de ton App Service
    BASE_URL = "https://histogramme-afd9fua3g2e9dqe0.eastus-01.azurewebsites.net"

    public_url = f"{BASE_URL}/static/{filename}"

    return {
        "image_url": public_url,
        "message": "Image generated successfully."
    }


# ---------------------------------------------------------
#  PARTIE 5 — GRAPHIQUE INTERACTIF (Plotly HTML)
# ---------------------------------------------------------

@app.post("/generate-chart-interactive")
def generate_chart_interactive(payload: ChartRequest):

    fig = go.Figure()

    if payload.chart_type == "line":
        fig.add_trace(go.Scatter(
            x=payload.labels,
            y=payload.values,
            mode='lines+markers',
            hovertemplate="Date: %{x}<br>Valeur: %{y}<extra></extra>"
        ))

    elif payload.chart_type == "bar":
        fig.add_trace(go.Bar(
            x=payload.labels,
            y=payload.values,
            hovertemplate="Catégorie: %{x}<br>Valeur: %{y}<extra></extra>"
        ))

    elif payload.chart_type == "pie":
        fig.add_trace(go.Pie(
            labels=payload.labels,
            values=payload.values,
            hovertemplate="%{label}: %{value}<extra></extra>"
        ))

    fig.update_layout(title=payload.title)

    # HTML
    html = fig.to_html(include_plotlyjs='cdn')

    file_id = uuid.uuid4()
    filename = f"graph_{file_id}.html"
    filepath = os.path.join("static", filename)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        return {"error": f"html saving error: {e}"}

    # ⚠️ Replace URL !
    BASE_URL = "https://histogramme-afd9fua3g2e9dqe0.eastus-01.azurewebsites.net"

    public_url = f"{BASE_URL}/static/{filename}"

    return {
        "interactive_url": public_url,
        "message": "Interactive graph generated successfully."
    }
