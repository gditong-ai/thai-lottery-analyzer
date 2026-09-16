import os
import re
from datetime import date, datetime
from typing import Optional

import httpx
import psycopg
from psycopg.rows import dict_row
from pythaidate import CsDate, to_julianday
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
APP_NAME = "Thai Lottery Analyzer"
APP_VERSION = "4.1.0"
GLO_BASE = "https://www.glo.or.th"
GLO_LATEST_URL = f"{GLO_BASE}/api/lottery/getLatestLottery"
GLO_YEAR_URL = f"{GLO_BASE}/api/lottery/getLotteryResultByYear"
GLO_HEADERS = {
    "Content-Type": "application/json",
    "Origin": GLO_BASE,
    "Referer": f"{GLO_BASE}/mission/awarding/orderby-time",
    "User-Agent": "Thai-Lottery-Analyzer/4.1",
}

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured.")

app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

WEEKDAYS = {1:"จันทร์",2:"อังคาร",3:"พุธ",4:"พฤหัสบดี",5:"ศุกร์",6:"เสาร์",7:"อาทิตย์"}
MONTHS = {1:"มกราคม",2:"กุมภาพันธ์",3:"มีนาคม",4:"เมษายน",5:"พฤษภาคม",6:"มิถุนายน",7:"กรกฎาคม",8:"สิงหาคม",9:"กันยายน",10:"ตุลาคม",11:"พฤศจิกายน",12:"ธันวาคม"}


def get_db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS draws (
                    id BIGSERIAL PRIMARY KEY,
                    draw_date DATE NOT NULL UNIQUE,
                    weekday INTEGER NOT NULL,
                    day INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    year_be INTEGER NOT NULL,
                    lunar_side VARCHAR(20) NOT NULL CHECK (lunar_side IN ('ข้างขึ้น','ข้างแรม')),
                    first_prize VARCHAR(6) NOT NULL,
                    last3_1 VARCHAR(3),
                    last3_2 VARCHAR(3),
                    last2 VARCHAR(2) NOT NULL,
                    source VARCHAR(50) DEFAULT 'GLO',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE draws ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'GLO'")
            cur.execute("ALTER TABLE draws ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_draws_date ON draws(draw_date)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_draws_filters ON draws(weekday,day,month,year_be,lunar_side)")
        conn.commit()


@app.on_event("startup")
def startup():
    init_db()


def normalize_number(value, digits):
    if value is None:
        return None
    s = re.sub(r"\D", "", str(value).strip())
    return s.zfill(digits)[-digits:] if s else None


def parse_date(value):
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            if d.year > 2400:
                d = d.replace(year=d.year - 543)
            return d
        except ValueError:
            pass
    raise ValueError(f"รูปแบบวันที่ไม่ถูกต้อง: {value}")


def lunar_side_for_date(d):
    cs = CsDate.fromjulianday(to_julianday(d.year, d.month, d.day))
    text = cs.csformat()
    return "ข้างขึ้น" if "ขึ้น" in text else "ข้างแรม"


def date_fields(draw_date):
    d = parse_date(draw_date)
    return {"draw_date":d,"weekday":d.weekday()+1,"day":d.day,"month":d.month,"year_be":d.year+543}


def validate_lunar_side(value):
    return value in ("ข้างขึ้น", "ข้างแรม")


def upsert_draw(cur, item, default_source="GLO"):
    fields = date_fields(item["draw_date"])
    first = normalize_number(item.get("first_prize"), 6)
    last3_1 = normalize_number(item.get("last3_1"), 3)
    last3_2 = normalize_number(item.get("last3_2"), 3)
    last2 = normalize_number(item.get("last2"), 2)
    lunar = item.get("lunar_side") or lunar_side_for_date(fields["draw_date"])
    source = item.get("source") or default_source
    if not first:
        raise ValueError("ไม่มีรางวัลที่ 1")
    if not last2:
        raise ValueError("ไม่มีเลขท้าย 2 ตัว")
    if not validate_lunar_side(lunar):
        raise ValueError("lunar_side ไม่ถูกต้อง")
    cur.execute("SELECT id FROM draws WHERE draw_date=%s", (fields["draw_date"],))
    exists = cur.fetchone()
    values = (fields["weekday"],fields["day"],fields["month"],fields["year_be"],lunar,first,last3_1,last3_2,last2,source,fields["draw_date"])
    if exists:
        cur.execute("""UPDATE draws SET weekday=%s,day=%s,month=%s,year_be=%s,lunar_side=%s,first_prize=%s,last3_1=%s,last3_2=%s,last2=%s,source=%s,updated_at=NOW() WHERE draw_date=%s""", values)
        return "updated"
    cur.execute("""INSERT INTO draws(draw_date,weekday,day,month,year_be,lunar_side,first_prize,last3_1,last3_2,last2,source) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (fields["draw_date"],)+values[:-1])
    return "inserted"


def import_items(items):
    inserted=updated=skipped=0
    errors=[]
    with get_db() as conn:
        with conn.cursor() as cur:
            for i,item in enumerate(items):
                try:
                    r=upsert_draw(cur,item,"GLO")
                    if r=="inserted": inserted+=1
                    else: updated+=1
                except Exception as e:
                    skipped+=1
                    if len(errors)<50: errors.append({"index":i,"error":str(e)})
        conn.commit()
    return {"inserted":inserted,"updated":updated,"skipped":skipped,"total":inserted+updated,"errors":errors}


def glo_entries_from_response(payload):
    if not isinstance(payload, dict):
        raise ValueError("GLO API ส่งข้อมูลรูปแบบไม่ถูกต้อง")
    if payload.get("status") is False:
        raise ValueError(payload.get("statusMessage") or "GLO API ไม่สำเร็จ")
    response = payload.get("response")
    if response is None and isinstance(payload.get("data"), list):
        response = payload["data"]
    if isinstance(response, dict):
        response=[response]
    if not isinstance(response,list):
        raise ValueError("ไม่พบ response จาก GLO API")
    result=[]
    for entry in response:
        if not isinstance(entry,dict) or not entry.get("date"):
            continue
        data=entry.get("data") or {}
        first=data.get("first") or []
        last2=data.get("last2") or []
        last3f=data.get("last3f") or []
        last3b=data.get("last3b") or []
        if not first or not last2:
            continue
        result.append({
            "draw_date":entry["date"],
            "first_prize":first[0],
            "last2":last2[0],
            "last3_1":last3b[0] if len(last3b)>0 else None,
            "last3_2":last3b[1] if len(last3b)>1 else None,
            "lunar_side":None,
            "source":"GLO"
        })
    return result


async def glo_post(url, payload=None):
    async with httpx.AsyncClient(timeout=45, headers=GLO_HEADERS, follow_redirects=True) as client:
        r=await client.post(url, json=payload or {})
        r.raise_for_status()
        return r.json()


@app.get("/health")
def health():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM draws")
            n=cur.fetchone()["count"]
    return {"ok":True,"database":"postgresql","draws":n,"version":APP_VERSION}


@app.get("/")
def root():
    return {"name":APP_NAME,"version":APP_VERSION,"status":"running","database":"postgresql","endpoints":{"health":"/health","database":"/api/database","options":"/api/options","draws":"/api/draws","analyze":"/api/analyze","glo_latest":"/api/glo/latest","glo_import_latest":"/api/glo/import-latest","glo_import_range":"/api/glo/import-range","docs":"/docs"}}


@app.get("/api/database")
def database_info():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total_draws,MIN(draw_date) AS oldest_draw,MAX(draw_date) AS newest_draw FROM draws")
            r=cur.fetchone()
    return {"ok":True,"database":"postgresql","total_draws":r["total_draws"],"oldest_draw":r["oldest_draw"].isoformat() if r["oldest_draw"] else None,"newest_draw":r["newest_draw"].isoformat() if r["newest_draw"] else None}


@app.get("/api/options")
def options():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT year_be FROM draws ORDER BY year_be DESC")
            years=cur.fetchall()
    return {"weekdays":[{"value":k,"label":v} for k,v in WEEKDAYS.items()],"days":list(range(1,32)),"months":[{"value":k,"label":v} for k,v in MONTHS.items()],"years":[{"value":r["year_be"],"label":str(r["year_be"])} for r in years],"lunar_sides":["ข้างขึ้น","ข้างแรม"]}


@app.get("/api/draws")
def list_draws(limit:int=Query(100,ge=1,le=5000)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,draw_date,weekday,day,month,year_be,lunar_side,first_prize,last3_1,last3_2,last2,source FROM draws ORDER BY draw_date DESC LIMIT %s",(limit,))
            rows=cur.fetchall()
    for r in rows: r["draw_date"]=r["draw_date"].isoformat()
    return {"ok":True,"count":len(rows),"rows":rows}


@app.post("/api/import")
def import_data(payload:dict):
    draws=payload.get("draws")
    if not isinstance(draws,list): raise HTTPException(400,"draws ต้องเป็น array")
    return {"ok":True,**import_items(draws)}


@app.post("/api/import/glo")
def import_glo(payload:dict):
    draws=payload.get("draws")
    if not isinstance(draws,list): raise HTTPException(400,"draws ต้องเป็น array")
    return {"ok":True,"source":"GLO",**import_items(draws)}


@app.post("/api/glo/import-latest")
async def import_glo_latest():
    try:
        raw=await glo_post(GLO_LATEST_URL)
        items=glo_entries_from_response(raw)
        if not items: raise ValueError("GLO ไม่ส่งผลรางวัลล่าสุดกลับมา")
        result=import_items(items)
        return {"ok":True,"source":"GLO","mode":"latest","fetched":len(items),**result}
    except httpx.HTTPError as e:
        raise HTTPException(502,f"เชื่อมต่อ GLO ไม่สำเร็จ: {e}")
    except ValueError as e:
        raise HTTPException(502,str(e))


@app.get("/api/glo/latest")
async def glo_latest():
    try:
        raw=await glo_post(GLO_LATEST_URL)
        items=glo_entries_from_response(raw)
        return {"ok":True,"source":"GLO","count":len(items),"draws":items}
    except Exception as e:
        raise HTTPException(502,f"อ่านข้อมูล GLO ไม่สำเร็จ: {e}")


@app.post("/api/glo/import-range")
async def import_glo_range(payload:dict):
    start_be=payload.get("start_year")
    end_be=payload.get("end_year")
    if not isinstance(start_be,int) or not isinstance(end_be,int): raise HTTPException(400,"start_year และ end_year ต้องเป็นปี พ.ศ.")
    if start_be>end_be: raise HTTPException(400,"start_year ต้องไม่มากกว่า end_year")
    if end_be-start_be>20: raise HTTPException(400,"นำเข้าครั้งละไม่เกิน 21 ปี")
    all_items=[]; api_errors=[]
    for be in range(start_be,end_be+1):
        try:
            raw=await glo_post(GLO_YEAR_URL,{"year":str(be-543)})
            items=glo_entries_from_response(raw)
            all_items.extend(items)
        except Exception as e:
            api_errors.append({"year_be":be,"error":str(e)})
    # Remove duplicates by date.
    unique={x["draw_date"]:x for x in all_items}
    result=import_items(list(unique.values())) if unique else {"inserted":0,"updated":0,"skipped":0,"total":0,"errors":[]}
    result["errors"]=api_errors+result["errors"]
    return {"ok":True,"source":"GLO","mode":"range","start_year":start_be,"end_year":end_be,"fetched":len(unique),**result}


@app.post("/api/import/range")
def import_range(payload:dict):
    draws=payload.get("draws",[])
    if not isinstance(draws,list): raise HTTPException(400,"draws ต้องเป็น array")
    return {"ok":True,"source":"GLO",**import_items(draws)}


@app.get("/api/analyze")
def analyze(weekday:Optional[int]=Query(None,ge=1,le=7),day:Optional[int]=Query(None,ge=1,le=31),month:Optional[int]=Query(None,ge=1,le=12),year_be:Optional[int]=Query(None),lunar_side:Optional[str]=Query(None)):
    conditions=[]; params=[]
    for name,value in (("weekday",weekday),("day",day),("month",month),("year_be",year_be),("lunar_side",lunar_side)):
        if value is not None:
            if name=="lunar_side" and not validate_lunar_side(value): raise HTTPException(400,"lunar_side ไม่ถูกต้อง")
            conditions.append(f"{name}=%s"); params.append(value)
    where="WHERE "+" AND ".join(conditions) if conditions else ""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT id,draw_date,weekday,day,month,year_be,lunar_side,first_prize,last3_1,last3_2,last2,source FROM draws {where} ORDER BY draw_date DESC",params)
            rows=cur.fetchall()
    exact={}; pairs={}; tens={}; units={}
    for r in rows:
        n=r["last2"]
        exact[n]=exact.get(n,0)+1
        pairs["".join(sorted(n))]=pairs.get("".join(sorted(n)),0)+1
        tens[n[0]]=tens.get(n[0],0)+1
        units[n[1]]=units.get(n[1],0)+1
        r["draw_date"]=r["draw_date"].isoformat()
    def ranked(d,key): return [{key:k,"count":v} for k,v in sorted(d.items(),key=lambda x:(-x[1],x[0]))]
    return {"ok":True,"count":len(rows),"rows":rows,"statistics":{"exact_last2":ranked(exact,"number"),"swapped_pair":ranked(pairs,"pair"),"tens":ranked(tens,"digit"),"units":ranked(units,"digit")}}


@app.get("/api/backtest")
def backtest(window:int=Query(12,ge=2,le=200),use_swap:bool=True):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT draw_date,last2 FROM draws ORDER BY draw_date DESC LIMIT %s",(window+1,))
            rows=cur.fetchall()
    tests=hits=0
    for i in range(len(rows)-1):
        target=rows[i]["last2"]
        prev=rows[i+1]["last2"]
        tests+=1
        candidates={prev}
        if use_swap: candidates.add(prev[::-1])
        if target in candidates: hits+=1
    return {"ok":True,"tests":tests,"hits":hits,"hit_rate":hits/tests if tests else 0}
