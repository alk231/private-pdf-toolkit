FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tini reaps child processes (Ghostscript, qpdf, ...). The other packages are used by the tools in Stages 2-3.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini qpdf ghostscript poppler-utils fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN mkdir -p /tmp/pdf-toolkit && chown -R appuser:appuser /app /tmp/pdf-toolkit
USER appuser

ENV PORT=10000 \
    WORK_DIR=/tmp/pdf-toolkit

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/v1/health' % os.environ.get('PORT', '10000'), timeout=3)"]

ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --no-access-log"]
