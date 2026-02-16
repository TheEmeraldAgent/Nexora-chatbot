from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "kb_chatbot_clean.db"

app = FastAPI(title="Nexora Customer SQL Chatbot")

app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/")
def home():
    return FileResponse(str(BASE / "static" / "index.html"))


@app.get("/api/search")
def search(q: str = Query(..., min_length=2, max_length=200), limit: int = 5):
    """
    Customer-facing search:
    - validated only
    - public only
    - content types: faq, troubleshooting, known_issue
    - ranked by FTS bm25
    """
    q_clean = q.replace('"', "").strip()

    sql_fts = """
    SELECT
      k.item_id,
      k.title,
      k.body,
      k.content_type,
      k.product,
      k.severity,
      k.updated_at,
      bm25(kb_item_fts) AS score
    FROM kb_item_fts
    JOIN kb_item k ON k.item_id = kb_item_fts.rowid
    WHERE k.status = 'validated'
      AND k.access_level = 'public'
      AND k.content_type IN ('known_issue','troubleshooting','faq')
      AND kb_item_fts MATCH ?
    ORDER BY
      CASE k.content_type
        WHEN 'known_issue' THEN 1
        WHEN 'troubleshooting' THEN 2
        WHEN 'faq' THEN 3
        ELSE 4
      END,
      score
    LIMIT ?;
    """

    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute(sql_fts, (q_clean, limit))
        rows = [dict(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        # Fallback if MATCH fails due to special characters
        sql_like = """
        SELECT item_id, title, body, content_type, product, severity, updated_at, 999999 AS score
        FROM kb_item
        WHERE status='validated'
          AND access_level='public'
          AND content_type IN ('known_issue','troubleshooting','faq')
          AND (LOWER(title) LIKE '%' || LOWER(?) || '%' OR LOWER(body) LIKE '%' || LOWER(?) || '%')
        ORDER BY updated_at DESC
        LIMIT ?;
        """
        cur.execute(sql_like, (q_clean, q_clean, limit))
        rows = [dict(r) for r in cur.fetchall()]

    conn.close()

    # Add short snippet for UI
    for r in rows:
        body = r.get("body") or ""
        r["snippet"] = body[:280] + ("…" if len(body) > 280 else "")

    return {"query": q, "results": rows}