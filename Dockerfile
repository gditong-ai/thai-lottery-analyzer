FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/main.py /app/backend/main.py
COPY dashboard /app/dashboard
COPY data /app/data
COPY frontend.py /app/frontend.py
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn","frontend:app","--host","0.0.0.0","--port","8000"]
