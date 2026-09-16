import os
import sqlite3
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", BASE / "data" / "lottery.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Thai Lottery Analyzer", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_date TEXT NOT NULL UNIQUE,
    weekday INTEGER NOT NULL,
    day INTEGER NOT NULL,
    month INTEGER NOT NULL,
    year_be INTEGER NOT NULL,
    lunar_side TEXT NOT NULL CHECK(lunar_side IN ('ข้างขึ้น','ข้างแรม')),
    first_prize TEXT NOT NULL,
    last3_1 TEXT,
    last3_2 TEXT,
    last2 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_draws_filter
ON draws(weekday, day, month, year_be, lunar_side, draw_date);
"""

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

init_db()

@app.get("/health")
def health():
    conn = db()
    count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    conn.close()
    return {"ok": True, "draws": count}

@app.get("/api/options")
def options():
    conn = db()
    years = [r[0] for r in conn.execute(
        "SELECT DISTINCT year_be FROM draws ORDER BY year_be DESC"
    ).fetchall()]
    conn.close()
    return {
        "weekdays": [
            {"value": 1, "label": "จันทร์"},
            {"value": 2, "label": "อังคาร"},
            {"value": 3, "label": "พุธ"},
            {"value": 4, "label": "พฤหัสบดี"},
            {"value": 5, "label": "ศุกร์"},
            {"value": 6, "label": "เสาร์"},
            {"value": 7, "label": "อาทิตย์"},
        ],
        "days": list(range(1, 32)),
        "months": [
            {"value": 1, "label": "มกราคม"}, {"value": 2, "label": "กุมภาพันธ์"},
            {"value": 3, "label": "มีนาคม"}, {"value": 4, "label": "เมษายน"},
            {"value": 5, "label": "พฤษภาคม"}, {"value": 6, "label": "มิถุนายน"},
            {"value": 7, "label": "กรกฎาคม"}, {"value": 8, "label": "สิงหาคม"},
            {"value": 9, "label": "กันยายน"}, {"value": 10, "label": "ตุลาคม"},
            {"value": 11, "label": "พฤศจิกายน"}, {"value": 12, "label": "ธันวาคม"},
        ],
        "years": years,
        "lunar_sides": ["ข้างขึ้น", "ข้างแรม"],
    }

@app.get("/api/analyze")
def analyze(
    weekday: int | None = Query(None, ge=1, le=7),
    day: int | None = Query(None, ge=1, le=31),
    month: int | None = Query(None, ge=1, le=12),
    year_be: int | None = Query(None),
    lunar_side: str | None = Query(None),
):
    filters = []
    params = []
    if weekday is not None:
        filters.append("weekday = ?"); params.append(weekday)
    if day is not None:
        filters.append("day = ?"); params.append(day)
    if month is not None:
        filters.append("month = ?"); params.append(month)
    if year_be is not None:
        filters.append("year_be = ?"); params.append(year_be)
    if lunar_side in ("ข้างขึ้น", "ข้างแรม"):
        filters.append("lunar_side = ?"); params.append(lunar_side)

    if not filters:
        return {"ok": False, "error": "กรุณาเลือกตัวกรองอย่างน้อย 1 รายการ"}

    where = " AND ".join(filters)
    conn = db()
    rows = conn.execute(
        f"""SELECT draw_date, weekday, day, month, year_be, lunar_side,
                   first_prize, last3_1, last3_2, last2
            FROM draws WHERE {where} ORDER BY draw_date DESC""",
        params
    ).fetchall()

    def pair_key(x):
        return "".join(sorted(x))

    last2_counts = {}
    tens_counts = {str(i): 0 for i in range(10)}
    units_counts = {str(i): 0 for i in range(10)}
    for r in rows:
        n = r["last2"].zfill(2)
        last2_counts[pair_key(n)] = last2_counts.get(pair_key(n), 0) + 1
        tens_counts[n[0]] += 1
        units_counts[n[1]] += 1

    top_pairs = sorted(
        [{"pair": k, "count": v} for k, v in last2_counts.items()],
        key=lambda x: (-x["count"], x["pair"])
    )[:20]

    conn.close()
    return {
        "ok": True,
        "count": len(rows),
        "rows": [dict(r) for r in rows],
        "statistics": {
            "last2_pairs": top_pairs,
            "tens": tens_counts,
            "units": units_counts,
        },
    }

@app.post("/api/import")
def import_draws(payload: list[dict]):
    """
    Import normalized records.
    Required: draw_date, lunar_side, first_prize, last2.
    Optional: last3_1, last3_2.
    draw_date must be YYYY-MM-DD (Gregorian).
    """
    conn = db()
    inserted = 0
    updated = 0
    for item in payload:
        dt = datetime.strptime(item["draw_date"], "%Y-%m-%d").date()
        lunar = item["lunar_side"]
        if lunar not in ("ข้างขึ้น", "ข้างแรม"):
            continue
        vals = (
            dt.isoformat(), dt.isoweekday(), dt.day, dt.month,
            int(item["year_be"]), lunar,
            str(item["first_prize"]).zfill(6),
            str(item.get("last3_1", "")).zfill(3) if item.get("last3_1") else None,
            str(item.get("last3_2", "")).zfill(3) if item.get("last3_2") else None,
            str(item["last2"]).zfill(2),
            datetime.utcnow().isoformat(timespec="seconds"),
        )
        cur = conn.execute("""
            INSERT INTO draws
            (draw_date,weekday,day,month,year_be,lunar_side,first_prize,
             last3_1,last3_2,last2,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(draw_date) DO UPDATE SET
              weekday=excluded.weekday, day=excluded.day, month=excluded.month,
              year_be=excluded.year_be, lunar_side=excluded.lunar_side,
              first_prize=excluded.first_prize, last3_1=excluded.last3_1,
              last3_2=excluded.last3_2, last2=excluded.last2
        """, vals)
        if cur.rowcount == 1:
            # SQLite reports 1 for both insert/update here; count as processed.
            inserted += 1
    conn.commit()
    conn.close()
    return {"ok": True, "processed": inserted}

app.mount("/assets", StaticFiles(directory=BASE / "dashboard"), name="assets")

@app.get("/")
def index():
    return FileResponse(BASE / "dashboard" / "index.html")
