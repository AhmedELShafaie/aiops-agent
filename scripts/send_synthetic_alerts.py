#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request


def build_payload(index: int) -> dict:
    metric_types = [
        ("cpu_usage", 92.0, 80.0),
        ("memory_pressure", 86.0, 75.0),
        ("disk_usage", 91.0, 85.0),
        ("network_saturation", 88.0, 78.0),
    ]
    metric, base_value, threshold = metric_types[index % len(metric_types)]
    return {
        "source": "prometheus",
        "host": f"staging-host-{index % 5}",
        "metric": metric,
        "value": round(base_value + random.uniform(-2.5, 3.0), 2),
        "threshold": threshold,
        "severity": "warning" if metric != "cpu_usage" else "critical",
        "tags": {"env": "staging", "team": "sre"},
    }


def post_json(url: str, payload: dict, client_id: str) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-client-id": client_id,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send synthetic alerts to ingest gateway.")
    parser.add_argument("--url", default="http://localhost:8001", help="Ingest gateway base URL")
    parser.add_argument("--count", type=int, default=20, help="Number of events to send")
    parser.add_argument("--client-id", default="staging-e2e", help="x-client-id header value")
    parser.add_argument("--sleep-ms", type=int, default=100, help="Delay between events in ms")
    args = parser.parse_args()

    endpoint = f"{args.url.rstrip('/')}/ingest"
    successes = 0
    for i in range(args.count):
        status, body = post_json(endpoint, build_payload(i), args.client_id)
        ok = 200 <= status < 300
        if ok:
            successes += 1
        print(f"[{i + 1}/{args.count}] status={status} ok={ok} body={body}")
        time.sleep(max(0, args.sleep_ms) / 1000.0)

    print(f"Completed: success={successes} failed={args.count - successes}")
    return 0 if successes == args.count else 1


if __name__ == "__main__":
    sys.exit(main())
