"""Inspect and wait for alerts, in Prometheus and in Grafana alerting.

    python -m lab.tools.alerts list
    python -m lab.tools.alerts wait BatchJobFailed firing --job daily_extract --timeout 300
    python -m lab.tools.alerts wait BatchJobFailed inactive --job daily_extract

Used by scripts/inject.sh, recover.sh and verify.sh. Exit code 0 when the expected
state was reached in every source, 1 on timeout.
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request

from lab import config

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "")


def _get(url: str, auth: tuple[str, str] | None = None) -> dict:
    req = urllib.request.Request(url)
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)


def prometheus_alerts() -> list[dict]:
    data = _get(f"{config.PROMETHEUS_URL}/api/v1/alerts")["data"]["alerts"]
    return [
        {"name": a["labels"]["alertname"], "job": a["labels"].get("job", ""), "state": a["state"]} for a in data
    ]  # state: pending | firing


def grafana_alerts() -> list[dict]:
    data = _get(f"{GRAFANA_URL}/api/prometheus/grafana/api/v1/alerts", (GRAFANA_USER, GRAFANA_PASSWORD))["data"][
        "alerts"
    ]
    # Grafana also lists instances in Normal state; those count as inactive.
    states = {"alerting": "firing", "pending": "pending", "normal": "inactive"}
    return [
        {
            "name": a["labels"]["alertname"],
            "job": a["labels"].get("job", ""),
            "state": states.get(a["state"].split(" ")[0].lower(), a["state"].lower()),
        }
        for a in data
    ]


SOURCES = {"prometheus": prometheus_alerts}
if GRAFANA_PASSWORD:
    SOURCES["grafana"] = grafana_alerts


def state_of(source: str, name: str, job: str | None) -> str:
    try:
        alerts = SOURCES[source]()
    except Exception as exc:  # noqa: BLE001
        return f"unreachable ({exc})"
    for a in alerts:
        if a["name"] == name and (job is None or a["job"] == job) and a["state"] != "inactive":
            return a["state"]
    return "inactive"


def cmd_list(_args) -> int:
    for source, fetch in SOURCES.items():
        try:
            alerts = [a for a in fetch() if a["state"] != "inactive"]
        except Exception as exc:  # noqa: BLE001
            print(f"{source:<10} unreachable: {exc}")
            continue
        if not alerts:
            print(f"{source:<10} no active alerts")
        for a in sorted(alerts, key=lambda a: (a["name"], a["job"])):
            print(f"{source:<10} {a['state']:<8} {a['name']:<30} {a['job']}")
    return 0


def cmd_wait(args) -> int:
    label = f"{args.alert}{'{job=' + args.job + '}' if args.job else ''}"
    pending = set(SOURCES)
    start = time.monotonic()
    while pending and time.monotonic() - start < args.timeout:
        for source in sorted(pending):
            state = state_of(source, args.alert, args.job)
            if state == args.state:
                print(f"  ✔ {source:<10} {label} is {state} after {time.monotonic() - start:.0f}s", flush=True)
                pending.discard(source)
        if pending:
            time.sleep(5)
    for source in sorted(pending):
        print(
            f"  ✘ {source:<10} {label} still {state_of(source, args.alert, args.job)} "
            f"after {args.timeout}s (expected {args.state})",
            flush=True,
        )
    return 1 if pending else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    wait = sub.add_parser("wait")
    wait.add_argument("alert")
    wait.add_argument("state", choices=["firing", "inactive"])
    wait.add_argument("--job")
    wait.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    sys.exit({"list": cmd_list, "wait": cmd_wait}[args.cmd](args))


if __name__ == "__main__":
    main()
