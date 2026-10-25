"""Status page: one line per batch job, computed from job_runs in PostgreSQL.

    GET  /         HTML page; <span id="overall-status"> is exactly OK, DEGRADED or KO
    GET  /health   same verdict as JSON (HTTP 503 unless OK)
    GET  /healthz  liveness of the web process itself (container healthcheck)
    POST /webhook/grafana   receives Grafana alert notifications and logs them

The synthetic check (synthetic/check.py) loads / like a user would.
"""

import html
import json
import os
import time
from datetime import datetime, timezone

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://lab:lab@postgres:5432/payments")
LOG_FILE = os.path.join(os.environ.get("LOG_DIR", "/var/log/lab"), "alert_notifications.log")
SCHEDULE_MINUTES = {
    "import_settlement_file": int(os.environ.get("IMPORT_EVERY_MIN", 5)),
    "reconcile_transactions": int(os.environ.get("RECONCILE_EVERY_MIN", 10)),
    "daily_extract": int(os.environ.get("EXTRACT_EVERY_MIN", 15)),
}

app = FastAPI(title="Night shift status page")

LATEST = """
SELECT DISTINCT ON (job) job, finished_at, status, error_type, message
FROM job_runs WHERE job = %s ORDER BY job, finished_at DESC"""
LAST_SUCCESS = """
SELECT max(finished_at) FILTER (WHERE status = 'success' AND did_work), min(started_at)
FROM job_runs WHERE job = %s"""


def evaluate() -> dict:
    now = datetime.now(timezone.utc)
    jobs = []
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
        slow = conn.execute("SELECT value FROM lab_faults WHERE name = 'slow_page'").fetchone()
        if slow:
            time.sleep(float(slow[0]))  # fault injection: scripts/inject.sh slow_page
        for job, minutes in SCHEDULE_MINUTES.items():
            last = conn.execute(LATEST, (job,)).fetchone()
            success, first_run = conn.execute(LAST_SUCCESS, (job,)).fetchone()
            # Never succeeded yet: measure from the first run (fresh start of the lab).
            since = success or first_run
            age = (now - since).total_seconds() if since else None
            if last is None:
                state, detail = "UNKNOWN", "never ran"
            elif last[2] == "failed":
                state, detail = "FAILED", f"{last[3]}: {last[4]}"
            elif age > 3 * minutes * 60:
                state, detail = "LATE", f"no successful run for {round(age / 60)} min"
            else:
                state, detail = "OK", ""
            jobs.append(
                {
                    "job": job,
                    "state": state,
                    "detail": detail,
                    "last_run": last[1].isoformat() if last else None,
                    "last_success": success.isoformat() if success else None,
                    "every_min": minutes,
                }
            )
    overall = "OK" if all(j["state"] == "OK" for j in jobs) else "DEGRADED"
    return {"overall": overall, "checked_at": now.isoformat(), "jobs": jobs}


def safe_evaluate() -> dict:
    try:
        return evaluate()
    except psycopg.Error as exc:
        return {
            "overall": "KO",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": f"database unreachable: {exc}".strip(),
            "jobs": [],
        }


COLORS = {
    "OK": "#16a34a",
    "DEGRADED": "#d97706",
    "KO": "#dc2626",
    "FAILED": "#dc2626",
    "LATE": "#d97706",
    "UNKNOWN": "#6b7280",
}


def _short(iso: str | None) -> str:
    """2026-10-25T11:27:00.680326+00:00 -> 2026-10-25 11:27:00 (the page header says UTC)."""
    return iso[:19].replace("T", " ") if iso else "—"


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    s = safe_evaluate()
    rows = "".join(
        f"<tr><td>{j['job']}</td><td style='color:{COLORS[j['state']]};font-weight:600'>{j['state']}</td>"
        f"<td>every&nbsp;{j['every_min']}&nbsp;min</td><td>{_short(j['last_success'])}</td>"
        f"<td>{html.escape(j['detail'])}</td></tr>"
        for j in s["jobs"]
    )
    error = f"<p class='err'>{html.escape(s['error'])}</p>" if "error" in s else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>Night shift — status</title>
<style>body{{font-family:system-ui,sans-serif;background:#0b0f17;color:#e5e7eb;margin:2rem}}
table{{border-collapse:collapse;width:100%;max-width:960px}}td,th{{border-bottom:1px solid #1f2937;
padding:.5rem;text-align:left}}.badge{{font-size:2rem;font-weight:800}}.err{{color:#fca5a5}}</style>
</head><body><h1>Payments batch — status</h1>
<p>Overall: <span id="overall-status" class="badge" style="color:{COLORS[s['overall']]}">{s['overall']}</span></p>
{error}<table><tr><th>Job</th><th>State</th><th>Schedule</th><th>Last success (UTC)</th><th>Detail</th></tr>
{rows}</table><p><small>Checked {s['checked_at']}</small></p></body></html>"""
    return HTMLResponse(page, status_code=200 if s["overall"] == "OK" else 503)


@app.get("/health")
def health() -> JSONResponse:
    s = safe_evaluate()
    return JSONResponse(s, status_code=200 if s["overall"] == "OK" else 503)


@app.get("/healthz")
def healthz() -> dict:
    return {"alive": True}


@app.post("/webhook/grafana")
async def grafana_webhook(request: Request) -> dict:
    """Stand-in for the on-call channel: each notification becomes a JSON log line
    (shipped to Kibana with the job logs)."""
    payload = await request.json()
    for alert in payload.get("alerts", []):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "job": "alert_notifications",
            "run_id": None,
            # Own level, so notifications don't inflate the job error counts in Kibana.
            "level": "ALERT" if alert.get("status") == "firing" else "INFO",
            "message": f"[{alert.get('status', '?').upper()}] {alert.get('labels', {}).get('alertname')}"
            f" {alert.get('annotations', {}).get('summary', '')}",
            "rows_processed": None,
            "duration_ms": None,
            "error_type": None,
            "alert_status": alert.get("status"),
            "alert_labels": alert.get("labels"),
        }
        line = json.dumps(record)
        print(line, flush=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return {"received": len(payload.get("alerts", []))}
