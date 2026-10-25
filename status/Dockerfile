FROM python:3.12.7-slim-bookworm

RUN pip install --no-cache-dir fastapi==0.115.2 uvicorn==0.32.0 "psycopg[binary]==3.2.3"

RUN useradd --uid 1000 --create-home lab && mkdir -p /var/log/lab && chown lab:lab /var/log/lab
WORKDIR /app
COPY app.py /app/app.py
USER lab
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
