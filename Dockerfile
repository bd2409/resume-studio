FROM python:3.12-slim

# LibreOffice converts Word to PDF; Carlito matches Calibri's metrics; poppler makes page previews.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

ENV DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
