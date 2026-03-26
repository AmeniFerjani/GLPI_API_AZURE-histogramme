# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import mysql.connector

# Pour les graphiques
import matplotlib.pyplot as plt
import pandas as pd
import base64
from io import BytesIO

app = FastAPI()

# ---------------------------------------------------------
#  PARTIE 1 — API SQL (inchangée, comme tu l'as déjà faite)
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
    # Si résultat = [[123]] ⇒ renvoyer {"value": 123}
    if rows and len(rows) == 1 and isinstance(rows[0], (list, tuple)) and len(rows[0]) == 1:
        return {"value": rows[0][0]}
    return {"result": rows}

@app.get("/healthz")
def healthz():
    return {"status": "ok"}



# ---------------------------------------------------------
#  PARTIE 2 — NOUVEL ENDPOINT POUR GÉNÉRER DES GRAPHIQUES
# ---------------------------------------------------------

class ChartRequest(BaseModel):
    labels: list
    values: list
    chart_type: str   # "bar", "line", "pie"
    title: str = ""

@app.post("/generate-chart")
def generate_chart(payload: ChartRequest):

    df = pd.DataFrame({
        "labels": payload.labels,
        "values": payload.values
    })

    fig, ax = plt.subplots(figsize=(6,4))

    chart = payload.chart_type.lower()

    if chart == "bar":
        ax.bar(df["labels"], df["values"])
    elif chart == "line":
        ax.plot(df["labels"], df["values"])
    elif chart == "pie":
        ax.pie(df["values"], labels=df["labels"], autopct='%1.1f%%')
    else:
        return {"error": "unsupported chart type"}

    ax.set_title(payload.title)
    plt.tight_layout()

    # Retour en base64
    buf = BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()

    return {"image_base64": b64}