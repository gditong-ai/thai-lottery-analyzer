import os
from datetime import datetime, date
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

APP_NAME = "Thai Lottery Analyzer"
APP_VERSION = "3.0.0"


if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured. "
        "Please add DATABASE_URL in Render Environment Variables."
    )


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
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
# CONSTANTS
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


# ============================================================
# DATABASE
# ============================================================

def get_db():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row
    )


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS draws (
                    id BIGSERIAL PRIMARY KEY,

                    draw_date DATE NOT NULL UNIQUE,

                    weekday INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    year_be INTEGER NOT NULL,

                    lunar_side VARCHAR(20) NOT NULL
                        CHECK (
                            lunar_side IN ('ข้างขึ้น', 'ข้างแรม')
                        ),

                    first_prize VARCHAR(6) NOT NULL,

                    last3_1 VARCHAR(3),
                    last3_2 VARCHAR(3),

                    last2 VARCHAR(2) NOT NULL,

                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_draws_filters
                ON draws (
                    weekday,
                    day,
                    month,
                    year_be,
                    lunar_side,
                    draw_date
                )
                """
            )

        conn.commit()


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup():
    init_db()


# ============================================================
# HELPERS
# ============================================================

def normalize_number(value, digits):
    if value is None:
        return None

    value = str(value).strip()

    value = "".join(
        ch for ch in value
        if ch.isdigit()
    )

    if not value:
        return None

    return value.zfill(digits)[-digits:]


def parse_date(value):
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
            return datetime.strptime(
                value,
                fmt
            ).date()
        except ValueError:
            continue

    raise ValueError(
        f"รูปแบบวันที่ไม่ถูกต้อง: {value}"
    )


def date_fields(draw_date):
    d = parse_date(draw_date)

    return {
        "draw_date": d,
        "weekday": d.weekday() + 1,
        "day": d.day,
        "month": d.month,
        "year_be": d.year + 543,
    }


def canonical_pair(value):
    value = normalize_number(value, 2)

    if not value:
        return None

    return "".join(sorted(value))


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    try:

        with get_db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    "SELECT COUNT(*) AS count FROM draws"
                )

                row = cur.fetchone()

        return {
            "ok": True,
            "database": "postgresql",
            "draws": row["count"],
            "version": APP_VERSION
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


# ============================================================
# DATABASE INFO
# ============================================================

@app.get("/api/database")
def database_info():

    try:

        with get_db() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_draws,
                        MIN(draw_date) AS oldest_draw,
                        MAX(draw_date) AS newest_draw
                    FROM draws
                    """
                )

                row = cur.fetchone()

        return {
            "ok": True,
            "database": "postgresql",
            "total_draws": row["total_draws"],
            "oldest_draw": (
                row["oldest_draw"].isoformat()
                if row["oldest_draw"]
                else None
            ),
            "newest_draw": (
                row["newest_draw"].isoformat()
                if row["newest_draw"]
                else None
            ),
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


# ============================================================
# OPTIONS
# ============================================================

@app.get("/api/options")
def options():

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT DISTINCT year_be
                FROM draws
                ORDER BY year_be DESC
                """
            )

            rows = cur.fetchall()

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

        "years": [
            {
                "value": row["year_be"],
                "label": str(row["year_be"])
            }
            for row in rows
        ],

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
    weekday: Optional[int] = Query(None),
    day: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    year_be: Optional[int] = Query(None),
    lunar_side: Optional[str] = Query(None),
):

    conditions = []
    params = []

    if weekday is not None:

        if not 1 <= weekday <= 7:
            raise HTTPException(
                status_code=400,
                detail="weekday ต้องอยู่ระหว่าง 1-7"
            )

        conditions.append("weekday = %s")
        params.append(weekday)

    if day is not None:

        if not 1 <= day <= 31:
            raise HTTPException(
                status_code=400,
                detail="day ต้องอยู่ระหว่าง 1-31"
            )

        conditions.append("day = %s")
        params.append(day)

    if month is not None:

        if not 1 <= month <= 12:
            raise HTTPException(
                status_code=400,
                detail="month ต้องอยู่ระหว่าง 1-12"
            )

        conditions.append("month = %s")
        params.append(month)

    if year_be is not None:

        conditions.append("year_be = %s")
        params.append(year_be)

    if lunar_side is not None:

        if lunar_side not in [
            "ข้างขึ้น",
            "ข้างแรม"
        ]:
            raise HTTPException(
                status_code=400,
                detail="lunar_side ไม่ถูกต้อง"
            )

        conditions.append(
            "lunar_side = %s"
        )
        params.append(lunar_side)

    if not conditions:

        raise HTTPException(
            status_code=400,
            detail="กรุณาเลือกตัวกรองอย่างน้อย 1 รายการ"
        )

    where_sql = " AND ".join(
        conditions
    )

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute(
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
            )

            rows = cur.fetchall()

    pair_counts = {}
    tens_counts = {}
    units_counts = {}

    result_rows = []

    for row in rows:

        item = dict(row)

        if item["draw_date"]:
            item["draw_date"] = (
                item["draw_date"].isoformat()
            )

        result_rows.append(item)

        pair = canonical_pair(
            row["last2"]
        )

        if pair:

            pair_counts[pair] = (
                pair_counts.get(pair, 0) + 1
            )

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
                "pair": k,
                "count": v
            }
            for k, v in pair_counts.items()
        ],
        key=lambda x: (
            -x["count"],
            x["pair"]
        )
    )

    tens_stats = sorted(
        [
            {
                "digit": k,
                "count": v
            }
            for k, v in tens_counts.items()
        ],
        key=lambda x: (
            -x["count"],
            x["digit"]
        )
    )

    units_stats = sorted(
        [
            {
                "digit": k,
                "count": v
            }
            for k, v in units_counts.items()
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
            "lunar_side": lunar_side
        },

        "count": len(result_rows),

        "rows": result_rows,

        "statistics": {
            "pairs": pair_stats,
            "tens": tens_stats,
            "units": units_stats
        }
    }


# ============================================================
# IMPORT DATA
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

    with get_db() as conn:
        with conn.cursor() as cur:

            for item in draws:

                try:

                    fields = date_fields(
                        item["draw_date"]
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

                    cur.execute(
                        """
                        SELECT id
                        FROM draws
                        WHERE draw_date = %s
                        """,
                        (fields["draw_date"],)
                    )

                    existing = cur.fetchone()

                    if existing:

                        cur.execute(
                            """
                            UPDATE draws
                            SET
                                weekday = %s,
                                day = %s,
                                month = %s,
                                year_be = %s,
                                lunar_side = %s,
                                first_prize = %s,
                                last3_1 = %s,
                                last3_2 = %s,
                                last2 = %s
                            WHERE draw_date = %s
                            """,
                            (
                                fields["weekday"],
                                fields["day"],
                                fields["month"],
                                fields["year_be"],
                                lunar_side,
                                first_prize,
                                last3_1,
                                last3_2,
                                last2,
                                fields["draw_date"],
                            )
                        )

                        updated += 1

                    else:

                        cur.execute(
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
                                last2
                            )
                            VALUES (
                                %s,%s,%s,%s,%s,
                                %s,%s,%s,%s,%s
                            )
                            """,
                            (
                                fields["draw_date"],
                                fields["weekday"],
                                fields["day"],
                                fields["month"],
                                fields["year_be"],
                                lunar_side,
                                first_prize,
                                last3_1,
                                last3_2,
                                last2,
                            )
                        )

                        inserted += 1

                except Exception:
                    skipped += 1

        conn.commit()

    return {
        "ok": True,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": inserted + updated
    }


# ============================================================
# DELETE ALL DATA
# ============================================================

@app.delete("/api/draws")
def delete_all_draws():

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute(
                "DELETE FROM draws"
            )

            deleted = cur.rowcount

        conn.commit()

    return {
        "ok": True,
        "deleted": deleted
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "database": "postgresql",

        "endpoints": {
            "health": "/health",
            "database": "/api/database",
            "options": "/api/options",
            "analyze": "/api/analyze",
            "import": "/api/import",
            "delete": "/api/draws",
            "docs": "/docs"
        }
    }
