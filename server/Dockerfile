FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/home/app
RUN apt-get update && apt-get install -y --no-install-recommends ghostscript libreoffice-writer libreoffice-calc libreoffice-impress qpdf tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-spa tesseract-ocr-fra tesseract-ocr-deu fonts-liberation && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 app
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /tmp/pdf-toolkit && chown -R app:app /srv /tmp/pdf-toolkit
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
