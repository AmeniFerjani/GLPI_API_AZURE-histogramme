# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import mysql.connector

# Matplotlib (PNG)
import matplotlib.pyplot as plt
import pandas as pd

# Plotly (Interactif HTML)
import plotly.graph_objects as go

# UUID + Fichiers statiques
import uuid
from fastapi.staticfiles import StaticFiles

app = FastAPI()


# ---------------------------------------------------------
# 1️⃣ PARTIE SQL (inchangée, testée et stable)
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
        return cur.fetchall()
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
    if rows and len(rows) == 1 and len(rows[0]) == 1:
        return {"value": rows[0][0]}
    return {"result": rows}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------
# 2️⃣ PARTIE STATIQUE (images + html)
# ---------------------------------------------------------

if not os.path.exists("static"):
    os.makedirs("static")

app.mount("/static", StaticFiles(directory="static"), name="static")

# ⚠️ CHANGE ICI AVEC TON URL APP SERVICE
BASE_URL = "https://histogramme-afd9fua3g2e9dqe0.eastus-01.azurewebsites.net"


# ---------------------------------------------------------
# 3️⃣ FORMAT D’ENTRÉE POUR LES GRAPHIQUES (nouvelle version)
# ---------------------------------------------------------

class ChartData(BaseModel):
    data: list        # ex: [ ["2023-01-01", 12], ["2023-01-02", 18] ]
    chart_type: str   # "line", "bar", "pie"
    title: str = ""


# ---------------------------------------------------------
# 4️⃣ GRAPHIQUE PNG (statique)
# ---------------------------------------------------------

@app.post("/generate-chart")
def generate_chart(payload: ChartData):

    # Extraction labels & valeurs
    try:
        labels = [str(row[0]) for row in payload.data]
        values = [float(row[1]) for row in payload.data]
    except:
        return {"error": "Invalid data format"}

    fig, ax = plt.subplots(figsize=(8, 4))

    chart = payload.chart_type.lower()

    try:
        if chart == "line":
            ax.plot(labels, values, marker="o")
        elif chart == "bar":
            ax.bar(labels, values)
        elif chart == "pie":
            ax.pie(values, labels=labels, autopct='%1.1f%%')
        else:
            return {"error": "Unsupported chart type"}
    except:
        return {"error": "Chart generation error"}

    ax.set_title(payload.title)
    plt.xticks(rotation=45)
    plt.tight_layout()

    filename = f"chart_{uuid.uuid4()}.png"
    filepath = os.path.join("static", filename)
    fig.savefig(filepath)

    image_url = f"{BASE_URL}/static/{filename}"

    return {"image_url": image_url}


# ---------------------------------------------------------
# 5️⃣ GRAPHIQUE INTERACTIF (Plotly HTML)
# ---------------------------------------------------------

@app.post("/generate-chart-interactive")
def generate_chart_interactive(payload: ChartData):

    try:
        labels = [str(row[0]) for row in payload.data]
        values = [float(row[1]) for row in payload.data]
    except:
        return {"error": "Invalid data format"}

    fig = go.Figure()

    chart = payload.chart_type.lower()

    if chart == "line":
        fig.add_trace(go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers",
            hovertemplate="Date: %{x}<br>Valeur: %{y}<extra></extra>"
        ))

    elif chart == "bar":
        fig.add_trace(go.Bar(
            x=labels,
            y=values,
            hovertemplate="Catégorie: %{x}<br>Valeur: %{y}<extra></extra>"
        ))

    elif chart == "pie":
        fig.add_trace(go.Pie(
            labels=labels,
            values=values,
            hovertemplate="%{label}: %{value}<extra></extra>"
        ))

    else:
        return {"error": "Unsupported chart type"}

    fig.update_layout(title=payload.title)

    html_code = fig.to_html(include_plotlyjs="cdn")

    filename = f"graph_{uuid.uuid4()}.html"
    filepath = os.path.join("static", filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_code)

    interactive_url = f"{BASE_URL}/static/{filename}"

    return {"interactive_url": interactive_url}
