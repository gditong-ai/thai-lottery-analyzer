# Thai Lottery Analyzer

เว็บวิเคราะห์ผลสลากย้อนหลังตามฟิลเตอร์ 5 ช่อง:
- วัน
- วันที่
- เดือน
- ปี
- ข้างขึ้น/ข้างแรม

ทุกช่องมีค่า "ไม่เลือก" และจะไม่แสดงผลจนกด "วิเคราะห์"

## API
- GET /health
- GET /api/options
- GET /api/analyze
- POST /api/import

## รูปแบบนำเข้าข้อมูล
POST /api/import เป็น JSON array เช่น:

[
  {
    "draw_date": "2026-01-02",
    "year_be": 2569,
    "lunar_side": "ข้างขึ้น",
    "first_prize": "837706",
    "last3_1": "347",
    "last3_2": "694",
    "last2": "16"
  }
]

หมายเหตุ: lunar_side ต้องกำหนดจากปฏิทินจันทรคติที่เชื่อถือได้ก่อนนำเข้าข้อมูล
