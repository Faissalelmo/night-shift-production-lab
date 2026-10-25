"""Synthetic user check (EKARA-style): open the status page in a real browser,
assert the overall status reads exactly "OK", and measure how long it took.

    python check.py           loop forever, every SYNTHETIC_EVERY_SECONDS
    python check.py --once    a single check (used by inject/recover scripts)

Pushes to the Pushgateway (job="synthetic_status_check"):
    synthetic_check_success               1 = page loaded and showed OK
    synthetic_check_duration_seconds      navigation start -> status text available
    synthetic_check_last_run_timestamp_seconds
    synthetic_check_interval_seconds
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from prometheus_client import CollectorRegistry, Gauge, pushadd_to_gateway

STATUS_URL = os.environ.get("STATUS_URL", "http://status:8000/")
PUSHGATEWAY_URL = os.environ.get("PUSHGATEWAY_URL", "pushgateway:9091")
INTERVAL = int(os.environ.get("SYNTHETIC_EVERY_SECONDS", 300))
TIMEOUT_MS = 15000
JOB = "synthetic_status_check"
LOG_FILE = os.path.join(os.environ.get("LOG_DIR", "/var/log/lab"), f"{JOB}.log")


def log(level: str, message: str, **fields) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "job": JOB,
        "run_id": fields.pop("run_id", None),
        "level": level,
        "message": message,
        "rows_processed": None,
        "duration_ms": fields.pop("duration_ms", None),
        "error_type": fields.pop("error_type", None),
        **fields,
    }
    line = json.dumps(record)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def check(browser) -> tuple[bool, float, str | None, str]:
    page = browser.new_page()
    start = time.monotonic()
    try:
        page.goto(STATUS_URL, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        text = page.locator("#overall-status").inner_text(timeout=TIMEOUT_MS).strip()
        duration = time.monotonic() - start
        if text == "OK":
            return True, duration, None, text
        return False, duration, "status_not_ok", text
    except PlaywrightError as exc:
        kind = "timeout" if "Timeout" in str(exc) else "page_unreachable"
        return False, time.monotonic() - start, kind, str(exc).splitlines()[0]
    finally:
        page.close()


def run_once(browser) -> None:
    run_id = f"syn-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    ok, duration, error_type, shown = check(browser)
    fields = {"run_id": run_id, "duration_ms": round(duration * 1000), "url": STATUS_URL, "shown": shown}
    if ok:
        log("INFO", f"status page OK in {duration:.2f}s", **fields)
    else:
        log("ERROR", f"status page check failed: {shown}", error_type=error_type, **fields)

    registry = CollectorRegistry()
    for name, value in {
        "synthetic_check_success": 1 if ok else 0,
        "synthetic_check_duration_seconds": duration,
        "synthetic_check_last_run_timestamp_seconds": time.time(),
        "synthetic_check_interval_seconds": INTERVAL,
    }.items():
        Gauge(name, name.replace("_", " "), registry=registry).set(value)
    try:
        pushadd_to_gateway(PUSHGATEWAY_URL, job=JOB, registry=registry, timeout=5)
    except Exception as exc:  # noqa: BLE001
        log("WARNING", f"could not push metrics: {exc}", error_type="pushgateway_unreachable")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        while True:
            run_once(browser)
            if args.once:
                break
            time.sleep(INTERVAL)
        browser.close()


if __name__ == "__main__":
    main()
