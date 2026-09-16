from fastapi import FastAPI
from fastapi.responses import FileResponse

from backend.main import app

# Replace the JSON health/info root with the actual dashboard.
# Keep every existing API route unchanged.
for route in list(app.routes):
    if getattr(route, "path", None) == "/":
        app.routes.remove(route)
        break

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse("/app/dashboard/index.html")
