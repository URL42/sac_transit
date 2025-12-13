FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY transit_server.py .

EXPOSE 8088

CMD ["uvicorn", "transit_server:app", "--host", "0.0.0.0", "--port", "8088", "--http", "h11"]
