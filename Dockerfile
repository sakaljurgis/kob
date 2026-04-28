FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py storage.py fetcher.py epub_builder.py ./
COPY templates/ ./templates/
COPY static/ ./static/

ENV DATA_DIR=/data \
    ARTICLES_PER_PAGE=8 \
    PORT=8080 \
    EPUB_SPLIT_THRESHOLD_BYTES=50000 \
    EPUB_SPLIT_TARGET_BYTES=25000

VOLUME /data

EXPOSE 8080

CMD gunicorn --workers 1 --bind 0.0.0.0:${PORT} --timeout 120 app:app
