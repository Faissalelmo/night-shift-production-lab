# Slim Python + Chromium only. The official Playwright image (3.1 GB) also ships
# Firefox and WebKit, which this check never uses.
FROM python:3.12.7-slim-bookworm

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir playwright==1.47.0 prometheus-client==0.21.0 \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

# Non-root, uid 1000 like the other lab images (they share the log volume).
RUN useradd --uid 1000 --create-home lab && mkdir -p /var/log/lab && chown lab:lab /var/log/lab
WORKDIR /app
COPY check.py /app/check.py
USER lab
CMD ["python", "check.py"]
