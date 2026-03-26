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
import uuid
from fastapi.staticfiles import StaticFiles

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
    if rows and len(rows) == 1 and isinstance(rows[0], (list, tuple)) and len(rows[0]) == 1:
        return {"value": rows[0][0]}
    return {"result": rows}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}



# ---------------------------------------------------------
#  PARTIE 2 — MODULE GRAPHIQUES + PUBLIC URL
# ---------------------------------------------------------

# Créer dossier static (si absent)
if not os.path.exists("static"):
    os.makedirs("static")

# Monter le dossier statique
app.mount("/static", StaticFiles(directory="static"), name="static")

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

    # 🔥 GENERATE UNIQUE FILE NAME
    file_id = uuid.uuid4()
    filename = f"chart_{file_id}.png"
    filepath = os.path.join("static", filename)

    # 🔥 SAVE PNG FILE!
    try:
        fig.savefig(filepath, format="png")
    except Exception as e:
        return {"error": f"file saving error: {e}"}

    # IMPORTANT : REMPLACE ICI PAR TON URL APP SERVICE !
    BASE_URL = "https://appservicegentixhistogramme-btevcspbxhqard7.eastus-01.azurewebsites.net"

    public_url = f"{BASE_URL}/static/{filename}"

    return {
        "image_url": public_url,
        "message": "Image generated successfully."
    }