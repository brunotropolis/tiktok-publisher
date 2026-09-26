# Playwright + Python (chromium e deps ja inclusos), casando a versao do playwright 1.63
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium

COPY server.py run_upload.py publicar_tiktok.py delete_last.py ./

ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
