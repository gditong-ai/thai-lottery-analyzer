import os
import json
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.getenv(
    "DATABASE_PATH",
    os.path.join(DATA_DIR, "lottery.db")
)

# สามารถกำหนด URL API ภายหลังผ่าน Render Environment Variable
GLO_API_URL = os.getenv("GLO_API_URL", "").strip()

APP_NAME = "Thai Lottery Analyzer"


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title=APP_NAME,
    version="2.0.0",
    description="ระบบรวบรวมและวิเคราะห์ผลสลากกินแบ่งรัฐบาล"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS draws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            draw_date TEXT NOT NULL UNIQUE,

            weekday INTEGER NOT NULL,
            day INTEGER NOT NULL,
            month INTEGER NOT NULL,
            year_be INTEGER NOT NULL,

            lunar_side TEXT NOT NULL
                CHECK(lunar_side IN ('ข้างขึ้น', 'ข้างแรม')),

            first_prize TEXT NOT NULL,

            last3_1 TEXT,
            last3_2 TEXT,

            last2 TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


# ============================================================
# BASIC HELPERS
# ============================================================

WEEKDAYS = {
    1: "จันทร์",
    2: "อังคาร",
    3: "พุธ",
    4: "พฤหัสบดี",
    5: "ศุกร์",
    6: "เสาร์",
    7: "อาทิตย์",
}

MONTHS = {
    1: "มกราคม",
    2: "กุมภาพันธ์",
    3: "มีนาคม",
    4: "เมษายน",
    5: "พฤษภาคม",
    6: "มิถุนายน",
    7: "กรกฎาคม",
    8: "สิงหาคม",
    9: "กันยายน",
    10: "ตุลาคม",
    11: "พฤศจิกายน",
    12: "ธันวาคม",
}


def normalize_number(value, digits):
    """
    แปลงเลขให้เป็น string ตามจำนวนหลัก
    เช่น
    7 -> 007
    27 -> 027
    """

    if value is None:
        return None

    value = str(value).strip()

    # เอาเฉพาะตัวเลข
    value = "".join(ch for ch in value if ch.isdigit())

    if not value:
        return None

    return value.zfill(digits)[-digits:]


def parse_date(value):
    """
    รองรับวันที่:
    YYYY-MM-DD
    DD/MM/YYYY
    DD-MM-YYYY
    """

    if isinstance(value, date):
        return value

    value = str(value).strip()

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    raise ValueError(
        f"รูปแบบวันที่ไม่ถูกต้อง: {value}"
    )


def calculate_date_fields(draw_date):
    """
    สร้างข้อมูล:
    weekday
    day
    month
    year_be
    """

    d = parse_date(draw_date)

    # Python:
    # Monday = 0
    # Sunday = 6
    weekday = d.weekday() + 1

    return {
        "draw_date": d.isoformat(),
        "weekday": weekday,
        "day": d.day,
        "month": d.month,
        "year_be": d.year + 543,
    }


def canonical_pair(value):
    """
    สำหรับเลข 2 ตัว

    27 และ 72
    จะถูกจัดเป็นกลุ่มเดียวกัน

    ตัวอย่าง:
    27 -> 27
    72 -> 27
    05 -> 05
    50 -> 05
    """

    value = normalize_number(value, 2)

    if not value:
        return None

    return "".join(sorted(value))


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    conn = get_db()

    row = conn.execute(
        "SELECT COUNT(*) AS count FROM draws"
    ).fetchone()

    conn.close()

    return {
        "ok": True,
        "draws": row["count"],
        "version": "2.0.0"
    }


# ============================================================
# OPTIONS
# ============================================================

@app.get("/api/options")
def options():

    conn = get_db()

    rows = conn.execute(
        """
        SELECT DISTINCT year_be
        FROM draws
        ORDER BY year_be DESC
        """
    ).fetchall()

    conn.close()

    years = [
        {
            "value": row["year_be"],
            "label": str(row["year_be"])
        }
        for row in rows
    ]

    return {
        "weekdays": [
            {
                "value": key,
                "label": value
            }
            for key, value in WEEKDAYS.items()
        ],

        "days": list(range(1, 32)),

        "months": [
            {
                "value": key,
                "label": value
            }
            for key, value in MONTHS.items()
        ],

        "years": years,

        "lunar_sides": [
            "ข้างขึ้น",
            "ข้างแรม"
        ]
    }


# ============================================================
# ANALYZE
# ============================================================

@app.get("/api/analyze")
def analyze(
    weekday: Optional[int] = Query(default=None),
    day: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
    year_be: Optional[int] = Query(default=None),
    lunar_side: Optional[str] = Query(default=None),
):

    filters = []

    if weekday is not None:
        if weekday < 1 or weekday > 7:
            raise HTTPException(
                status_code=400,
                detail="weekday ต้องอยู่ระหว่าง 1-7"
            )

        filters.append(
            ("weekday", weekday)
        )

    if day is not None:
        if day < 1 or day > 31:
            raise HTTPException(
                status_code=400,
                detail="day ต้องอยู่ระหว่าง 1-31"
            )

        filters.append(
            ("day", day)
        )

    if month is not None:
        if month < 1 or month > 12:
            raise HTTPException(
                status_code=400,
                detail="month ต้องอยู่ระหว่าง 1-12"
            )

        filters.append(
            ("month", month)
        )

    if year_be is not None:
        filters.append(
            ("year_be", year_be)
        )

    if lunar_side is not None:

        if lunar_side not in [
            "ข้างขึ้น",
            "ข้างแรม"
        ]:
            raise HTTPException(
                status_code=400,
                detail="lunar_side ต้องเป็น ข้างขึ้น หรือ ข้างแรม"
            )

        filters.append(
            ("lunar_side", lunar_side)
        )

    # ต้องเลือกอย่างน้อย 1 filter
    if not filters:
        raise HTTPException(
            status_code=400,
            detail="กรุณาเลือกตัวกรองอย่างน้อย 1 รายการ"
        )

    where = []
    params = []

    for field, value in filters:
        where.append(f"{field} = ?")
        params.append(value)

    where_sql = " AND ".join(where)

    conn = get_db()

    rows = conn.execute(
        f"""
        SELECT
            id,
            draw_date,
            weekday,
            day,
            month,
            year_be,
            lunar_side,
            first_prize,
            last3_1,
            last3_2,
            last2
        FROM draws
        WHERE {where_sql}
        ORDER BY draw_date DESC
        """,
        params
    ).fetchall()

    conn.close()

    result_rows = []

    pair_counts = {}
    tens_counts = {}
    units_counts = {}

    for row in rows:

        item = dict(row)

        result_rows.append(item)

        # -----------------------------
        # 2 DIGIT PAIR
        # -----------------------------

        pair = canonical_pair(
            row["last2"]
        )

        if pair:
            pair_counts[pair] = (
                pair_counts.get(pair, 0) + 1
            )

        # -----------------------------
        # TENS
        # -----------------------------

        last2 = normalize_number(
            row["last2"],
            2
        )

        if last2:

            tens = last2[0]
            units = last2[1]

            tens_counts[tens] = (
                tens_counts.get(tens, 0) + 1
            )

            units_counts[units] = (
                units_counts.get(units, 0) + 1
            )

    pair_stats = sorted(
        [
            {
                "pair": key,
                "count": value
            }
            for key, value in pair_counts.items()
        ],
        key=lambda x: (
            -x["count"],
            x["pair"]
        )
    )

    tens_stats = sorted(
        [
            {
                "digit": key,
                "count": value
            }
            for key, value in tens_counts.items()
        ],
        key=lambda x: (
            -x["count"],
            x["digit"]
        )
    )

    units_stats = sorted(
        [
            {
                "digit": key,
                "count": value
            }
            for key, value in units_counts.items()
        ],
        key=lambda x: (
            -x["count"],
            x["digit"]
        )
    )

    return {
        "ok": True,

        "filters": {
            "weekday": weekday,
            "day": day,
            "month": month,
            "year_be": year_be,
            "lunar_side": lunar_side,
        },

        "count": len(result_rows),

        "rows": result_rows,

        "stats": {
            "pair": pair_stats,
            "tens": tens_stats,
            "units": units_stats,
        }
    }


# ============================================================
# IMPORT NORMALIZED DATA
# ============================================================

@app.post("/api/import")
def import_data(payload: dict):

    draws = payload.get("draws")

    if not isinstance(draws, list):
        raise HTTPException(
            status_code=400,
            detail="payload ต้องมี draws เป็น array"
        )

    inserted = 0
    updated = 0
    skipped = 0

    conn = get_db()

    for item in draws:

        try:

            draw_date = item.get("draw_date")

            if not draw_date:
                skipped += 1
                continue

            date_fields = calculate_date_fields(
                draw_date
            )

            first_prize = normalize_number(
                item.get("first_prize"),
                6
            )

            last3_1 = normalize_number(
                item.get("last3_1"),
                3
            )

            last3_2 = normalize_number(
                item.get("last3_2"),
                3
            )

            last2 = normalize_number(
                item.get("last2"),
                2
            )

            lunar_side = item.get(
                "lunar_side"
            )

            if lunar_side not in [
                "ข้างขึ้น",
                "ข้างแรม"
            ]:
                skipped += 1
                continue

            if not first_prize or not last2:
                skipped += 1
                continue

            now = datetime.utcnow().isoformat()

            existing = conn.execute(
                """
                SELECT id
                FROM draws
                WHERE draw_date = ?
                """,
                (
                    date_fields["draw_date"],
                )
            ).fetchone()

            if existing:

                conn.execute(
                    """
                    UPDATE draws
                    SET
                        weekday = ?,
                        day = ?,
                        month = ?,
                        year_be = ?,
                        lunar_side = ?,
                        first_prize = ?,
                        last3_1 = ?,
                        last3_2 = ?,
                        last2 = ?
                    WHERE draw_date = ?
                    """,
                    (
                        date_fields["weekday"],
                        date_fields["day"],
                        date_fields["month"],
                        date_fields["year_be"],
                        lunar_side,
                        first_prize,
                        last3_1,
                        last3_2,
                        last2,
                        date_fields["draw_date"],
                    )
                )

                updated += 1

            else:

                conn.execute(
                    """
                    INSERT INTO draws (
                        draw_date,
                        weekday,
                        day,
                        month,
                        year_be,
                        lunar_side,
                        first_prize,
                        last3_1,
                        last3_2,
                        last2,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        date_fields["draw_date"],
                        date_fields["weekday"],
                        date_fields["day"],
                        date_fields["month"],
                        date_fields["year_be"],
                        lunar_side,
                        first_prize,
                        last3_1,
                        last3_2,
                        last2,
                        now,
                    )
                )

                inserted += 1

        except Exception:
            skipped += 1

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": inserted + updated
    }


# ============================================================
# GLO API HELPER
# ============================================================

def fetch_json(url):
    """
    เรียก API แบบ server-side

    ใช้ urllib ของ Python
    จึงไม่ต้องติดตั้ง requests/httpx
    """

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "ThaiLotteryAnalyzer/2.0"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            raw = response.read()

            return json.loads(
                raw.decode("utf-8")
            )

    except urllib.error.HTTPError as e:

        raise HTTPException(
            status_code=502,
            detail=f"GLO API HTTP Error: {e.code}"
        )

    except urllib.error.URLError as e:

        raise HTTPException(
            status_code=502,
            detail=f"GLO API connection error: {e.reason}"
        )

    except json.JSONDecodeError:

        raise HTTPException(
            status_code=502,
            detail="GLO API ส่งข้อมูลที่ไม่ใช่ JSON"
        )


# ============================================================
# IMPORT FROM GLO
# ============================================================

@app.post("/api/import/glo")
def import_from_glo(
    api_url: Optional[str] = Query(default=None)
):

    """
    จุดเชื่อมต่อข้อมูล GLO

    ลำดับความสำคัญ:
    1. api_url ที่ส่งเข้ามา
    2. GLO_API_URL ใน Environment Variable

    ยังไม่เดา endpoint ของ GLO
    ถ้ายังไม่มี URL ที่ยืนยัน ระบบจะตอบกลับให้กำหนด URL ก่อน
    """

    target_url = (
        api_url.strip()
        if api_url
        else GLO_API_URL
    )

    if not target_url:

        raise HTTPException(
            status_code=400,
            detail={
                "message":
                    "ยังไม่ได้กำหนด GLO API URL",
                "next_step":
                    "ตั้งค่า GLO_API_URL ใน Render Environment Variables"
            }
        )

    data = fetch_json(target_url)

    return {
        "ok": True,
        "source": "GLO",
        "message":
            "เชื่อมต่อแหล่งข้อมูลสำเร็จ แต่ต้องตรวจรูปแบบข้อมูลก่อนนำเข้า",
        "data": data
    }


# ============================================================
# DATABASE SUMMARY
# ============================================================

@app.get("/api/database")
def database_summary():

    conn = get_db()

    total = conn.execute(
        "SELECT COUNT(*) AS count FROM draws"
    ).fetchone()["count"]

    oldest = conn.execute(
        "SELECT MIN(draw_date) AS value FROM draws"
    ).fetchone()["value"]

    newest = conn.execute(
        "SELECT MAX(draw_date) AS value FROM draws"
    ).fetchone()["value"]

    conn.close()

    return {
        "ok": True,
        "total_draws": total,
        "oldest_draw": oldest,
        "newest_draw": newest,
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "name": APP_NAME,
        "version": "2.0.0",
        "status": "running",

        "endpoints": {
            "health": "/health",
            "options": "/api/options",
            "analyze": "/api/analyze",
            "database": "/api/database",
            "import": "/api/import",
            "glo_import": "/api/import/glo",
            "docs": "/docs",
        }
    }
