import os
import re
from datetime import date, datetime
from typing import Optional

import httpx
import psycopg
from psycopg.rows import dict_row

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

APP_NAME = "Thai Lottery Analyzer"
APP_VERSION = "4.0.0"

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured."
    )


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "ระบบรวบรวมผลสลากกินแบ่งรัฐบาล "
        "และวิเคราะห์ข้อมูลย้อนหลัง"
    )
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
                            lunar_side IN (
                                'ข้างขึ้น',
                                'ข้างแรม'
                            )
                        ),

                    first_prize VARCHAR(6) NOT NULL,

                    last3_1 VARCHAR(3),
                    last3_2 VARCHAR(3),

                    last2 VARCHAR(2) NOT NULL,

                    source VARCHAR(50)
                        DEFAULT 'GLO',

                    created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW()
                )
                """
            )

            cur.execute(
                """
                ALTER TABLE draws
                ADD COLUMN IF NOT EXISTS source
                VARCHAR(50) DEFAULT 'GLO'
                """
            )

            cur.execute(
                """
                ALTER TABLE draws
                ADD COLUMN IF NOT EXISTS updated_at
                TIMESTAMPTZ DEFAULT NOW()
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_draws_date
                ON draws(draw_date)
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_draws_filters
                ON draws(
                    weekday,
                    day,
                    month,
                    year_be,
                    lunar_side
                )
                """
            )

        conn.commit()


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

    value = re.sub(
        r"\D",
        "",
        value
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
            pass

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

    value = normalize_number(
        value,
        2
    )

    if not value:
        return None

    return "".join(
        sorted(value)
    )


def validate_lunar_side(value):

    return value in [
        "ข้างขึ้น",
        "ข้างแรม"
    ]


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

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
            "draws": "/api/draws",
            "analyze": "/api/analyze",
            "import": "/api/import",
            "import_glo": "/api/import/glo",
            "import_range": "/api/import/range",
            "delete": "/api/draws",
            "docs": "/docs"
        }
    }


# ============================================================
# DATABASE INFO
# ============================================================

@app.get("/api/database")
def database_info():

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
        )
    }


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
                "value": k,
                "label": v
            }
            for k, v in WEEKDAYS.items()
        ],

        "days": list(range(1, 32)),

        "months": [
            {
                "value": k,
                "label": v
            }
            for k, v in MONTHS.items()
        ],

        "years": [
            {
                "value": r["year_be"],
                "label": str(r["year_be"])
            }
            for r in rows
        ],

        "lunar_sides": [
            "ข้างขึ้น",
            "ข้างแรม"
        ]
    }


# ============================================================
# LIST DRAWS
# ============================================================

@app.get("/api/draws")
def list_draws(
    limit: int = Query(100, ge=1, le=5000)
):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
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
                    last2,
                    source
                FROM draws
                ORDER BY draw_date DESC
                LIMIT %s
                """,
                (limit,)
            )

            rows = cur.fetchall()

    result = []

    for row in rows:

        item = dict(row)

        if item["draw_date"]:
            item["draw_date"] = (
                item["draw_date"].isoformat()
            )

        result.append(item)

    return {
        "ok": True,
        "count": len(result),
        "rows": result
    }


# ============================================================
# IMPORT CORE
# ============================================================

def upsert_draw(
    cur,
    item,
    default_source="GLO"
):

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

    source = (
        item.get("source")
        or default_source
    )

    if not first_prize:
        raise ValueError(
            "ไม่มีรางวัลที่ 1"
        )

    if not last2:
        raise ValueError(
            "ไม่มีเลขท้าย 2 ตัว"
        )

    if not validate_lunar_side(
        lunar_side
    ):
        raise ValueError(
            "lunar_side ต้องเป็น "
            "ข้างขึ้น หรือ ข้างแรม"
        )

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
                last2 = %s,
                source = %s,
                updated_at = NOW()
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
                source,
                fields["draw_date"]
            )
        )

        return "updated"

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
            last2,
            source
        )
        VALUES (
            %s,%s,%s,%s,%s,
            %s,%s,%s,%s,%s,%s
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
            source
        )
    )

    return "inserted"


# ============================================================
# IMPORT GENERIC
# ============================================================

@app.post("/api/import")
def import_data(payload: dict):

    draws = payload.get("draws")

    if not isinstance(draws, list):
        raise HTTPException(
            status_code=400,
            detail="draws ต้องเป็น array"
        )

    inserted = 0
    updated = 0
    skipped = 0
    errors = []

    with get_db() as conn:

        with conn.cursor() as cur:

            for index, item in enumerate(draws):

                try:

                    result = upsert_draw(
                        cur,
                        item,
                        "GLO"
                    )

                    if result == "inserted":
                        inserted += 1

                    else:
                        updated += 1

                except Exception as e:

                    skipped += 1

                    if len(errors) < 20:

                        errors.append({
                            "index": index,
                            "error": str(e)
                        })

        conn.commit()

    return {
        "ok": True,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": inserted + updated,
        "errors": errors
    }


# ============================================================
# GLO IMPORT
#
# This endpoint accepts a normalized GLO payload.
# The official GLO catalog is the authoritative source.
# ============================================================

@app.post("/api/import/glo")
def import_glo(payload: dict):

    draws = payload.get("draws")

    if not isinstance(draws, list):

        raise HTTPException(
            status_code=400,
            detail=(
                "draws ต้องเป็น array "
                "ของข้อมูลจาก GLO"
            )
        )

    inserted = 0
    updated = 0
    skipped = 0
    errors = []

    with get_db() as conn:

        with conn.cursor() as cur:

            for index, raw in enumerate(draws):

                try:

                    item = dict(raw)

                    item["source"] = "GLO"

                    result = upsert_draw(
                        cur,
                        item,
                        "GLO"
                    )

                    if result == "inserted":
                        inserted += 1
                    else:
                        updated += 1

                except Exception as e:

                    skipped += 1

                    if len(errors) < 50:

                        errors.append({
                            "index": index,
                            "error": str(e)
                        })

        conn.commit()

    return {
        "ok": True,
        "source": "GLO",
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": inserted + updated,
        "errors": errors
    }


# ============================================================
# IMPORT RANGE
#
# Accepts a prepared list of official GLO results and
# records the requested range metadata.
# ============================================================

@app.post("/api/import/range")
def import_range(payload: dict):

    start_year = payload.get(
        "start_year"
    )

    end_year = payload.get(
        "end_year"
    )

    draws = payload.get(
        "draws",
        []
    )

    if not isinstance(
        start_year,
        int
    ) or not isinstance(
        end_year,
        int
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "start_year และ end_year "
                "ต้องเป็นตัวเลข พ.ศ."
            )
        )

    if start_year > end_year:

        raise HTTPException(
            status_code=400,
            detail=(
                "start_year ต้องไม่มากกว่า "
                "end_year"
            )
        )

    if not isinstance(
        draws,
        list
    ):

        raise HTTPException(
            status_code=400,
            detail="draws ต้องเป็น array"
        )

    inserted = 0
    updated = 0
    skipped = 0
    errors = []

    with get_db() as conn:

        with conn.cursor() as cur:

            for index, item in enumerate(draws):

                try:

                    result = upsert_draw(
                        cur,
                        item,
                        "GLO"
                    )

                    if result == "inserted":
                        inserted += 1
                    else:
                        updated += 1

                except Exception as e:

                    skipped += 1

                    if len(errors) < 50:

                        errors.append({
                            "index": index,
                            "error": str(e)
                        })

        conn.commit()

    return {
        "ok": True,
        "source": "GLO",
        "range": {
            "start_year": start_year,
            "end_year": end_year
        },
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": inserted + updated,
        "errors": errors
    }


# ============================================================
# ANALYSIS
# ============================================================

@app.get("/api/analyze")
def analyze(

    weekday: Optional[int] = Query(
        None,
        ge=1,
        le=7
    ),

    day: Optional[int] = Query(
        None,
        ge=1,
        le=31
    ),

    month: Optional[int] = Query(
        None,
        ge=1,
        le=12
    ),

    year_be: Optional[int] = Query(
        None
    ),

    lunar_side: Optional[str] = Query(
        None
    )
):

    conditions = []
    params = []

    if weekday is not None:

        conditions.append(
            "weekday = %s"
        )

        params.append(weekday)

    if day is not None:

        conditions.append(
            "day = %s"
        )

        params.append(day)

    if month is not None:

        conditions.append(
            "month = %s"
        )

        params.append(month)

    if year_be is not None:

        conditions.append(
            "year_be = %s"
        )

        params.append(year_be)

    if lunar_side is not None:

        if not validate_lunar_side(
            lunar_side
        ):

            raise HTTPException(
                status_code=400,
                detail="lunar_side ไม่ถูกต้อง"
            )

        conditions.append(
            "lunar_side = %s"
        )

        params.append(
            lunar_side
        )

    where_sql = ""

    if conditions:

        where_sql = (
            "WHERE "
            + " AND ".join(
                conditions
            )
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
                    last2,
                    source
                FROM draws
                {where_sql}
                ORDER BY draw_date DESC
                """,
                params
            )

            rows = cur.fetchall()

    pair_counts = {}
    exact_counts = {}
    tens_counts = {}
    units_counts = {}

    result_rows = []

    for row in rows:

        item = dict(row)

        item["draw_date"] = (
            item["draw_date"].isoformat()
        )

        result_rows.append(item)

        last2 = normalize_number(
            row["last2"],
            2
        )

        if not last2:
            continue

        exact_counts[last2] = (
            exact_counts.get(
                last2,
                0
            ) + 1
        )

        pair = canonical_pair(
            last2
        )

        pair_counts[pair] = (
            pair_counts.get(
                pair,
                0
            ) + 1
        )

        tens = last2[0]
        units = last2[1]

        tens_counts[tens] = (
            tens_counts.get(
                tens,
                0
            ) + 1
        )

        units_counts[units] = (
            units_counts.get(
                units,
                0
            ) + 1
        )

    def sorted_counts(
        source,
        key_name
    ):

        return sorted(
            [
                {
                    key_name: k,
                    "count": v
                }
                for k, v in source.items()
            ],
            key=lambda x: (
                -x["count"],
                x[key_name]
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

            "exact_last2": sorted_counts(
                exact_counts,
                "number"
            ),

            "swapped_pair": sorted_counts(
                pair_counts,
                "pair"
            ),

            "tens": sorted_counts(
                tens_counts,
                "digit"
            ),

            "units": sorted_counts(
                units_counts,
                "digit"
            )
        }
    }


# ============================================================
# BACKTEST
#
# Descriptive historical test only.
# It does not claim future prediction.
# ============================================================

@app.get("/api/backtest")
def backtest(

    window: int = Query(
        12,
        ge=2,
        le=200
    ),

    use_swap: bool = True
):

    with get_db() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    draw_date,
                    last2
                FROM draws
                ORDER BY draw_date ASC
                """
            )

            rows = cur.fetchall()

    if len(rows) <= window:

        return {
            "ok": True,
            "draws": len(rows),
            "window": window,
            "tests": 0,
            "message": (
                "ข้อมูลยังไม่เพียงพอสำหรับ "
                "การทดสอบย้อนหลัง"
            )
        }

    tests = []

    for i in range(
        window,
        len(rows)
    ):

        history = rows[
            i - window:i
        ]

        target = normalize_number(
            rows[i]["last2"],
            2
        )

        frequency = {}

        for h in history:

            value = normalize_number(
                h["last2"],
                2
            )

            if not value:
                continue

            keys = [value]

            if use_swap:
                keys.append(
                    value[::-1]
                )

            for key in set(keys):

                frequency[key] = (
                    frequency.get(
                        key,
                        0
                    ) + 1
                )

        if not frequency:
            continue

        ranked = sorted(
            frequency.items(),
            key=lambda x: (
                -x[1],
                x[0]
            )
        )

        candidate = ranked[0][0]

        if use_swap:

            hit = (
                candidate == target
                or candidate[::-1] == target
            )

        else:

            hit = (
                candidate == target
            )

        tests.append({
            "target_date": (
                rows[i]["draw_date"].isoformat()
            ),
            "target": target,
            "candidate": candidate,
            "hit": hit
        })

    hits = sum(
        1
        for x in tests
        if x["hit"]
    )

    total = len(tests)

    hit_rate = (
        hits / total
        if total
        else 0
    )

    return {

        "ok": True,

        "window": window,

        "use_swap": use_swap,

        "tests": total,

        "hits": hits,

        "hit_rate": hit_rate,

        "results": tests
    }


# ============================================================
# DELETE
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
