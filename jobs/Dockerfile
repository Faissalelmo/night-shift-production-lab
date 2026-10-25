FROM python:3.12.7-slim-bookworm

# supercronic: cron for containers (reads a standard crontab, logs to stdout,
# forwards signals). Checksums pinned per architecture.
ARG SUPERCRONIC_VERSION=v0.2.33
ARG TARGETARCH
RUN set -eu; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl procps; \
    rm -rf /var/lib/apt/lists/*; \
    case "${TARGETARCH:-amd64}" in \
        amd64) sha=71b0d58cc53f6bd72cf2f293e09e294b79c666d8 ;; \
        arm64) sha=e0f0c06ebc5627e43b25475711e694450489ab00 ;; \
        *) echo "unsupported arch ${TARGETARCH}"; exit 1 ;; \
    esac; \
    curl -fsSLo /usr/local/bin/supercronic \
        "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH:-amd64}"; \
    echo "${sha}  /usr/local/bin/supercronic" | sha1sum -c -; \
    chmod +x /usr/local/bin/supercronic

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Non-root, uid 1000 (matches the status image, which shares the log volume).
RUN useradd --uid 1000 --create-home lab \
 && mkdir -p /app /data/inbox /data/archive /data/outbox /var/log/lab \
 && chown -R lab:lab /app /data /var/log/lab

WORKDIR /app
COPY --chown=lab:lab lab /app/lab
COPY --chmod=755 run-job /usr/local/bin/run-job
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

USER lab
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
