# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import mysql.connector

app = FastAPI()

class SQLQuery(BaseModel):
    query: str

def get_db_conn():
    try:
        # ⚠️ On lira ces variables depuis les App Settings Azure (voir plus bas)
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

# (Optionnel) endpoint santé
@app.get("/healthz")
def healthz():
    return {"status": "ok"}
