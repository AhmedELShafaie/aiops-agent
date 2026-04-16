#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request


def load_secret(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def sign_payload(secret: str, timestamp: str, body: str) -> str:
    message = f"{timestamp}.{body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Send signed ingest request (for nginx HMAC validation).")
    parser.add_argument("--url", required=True, help="Ingest URL")
    parser.add_argument("--secret-file", required=True, help="Path to HMAC secret file")
    parser.add_argument("--api-key", required=True, help="x-api-key configured in nginx")
    args = parser.parse_args()

    payload = {
        "source": "prometheus",
        "host": "signed-test-host",
        "metric": "cpu_usage",
        "value": 91.3,
        "threshold": 80.0,
        "severity": "warning",
        "tags": {"env": "staging", "team": "sre"},
    }
    body = json.dumps(payload, separators=(",", ":"))
    ts = str(int(time.time()))
    secret = load_secret(args.secret_file)
    signature = sign_payload(secret, ts, body)

    req = urllib.request.Request(
        args.url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": args.api_key,
            "x-signature-timestamp": ts,
            "x-signature": signature,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            print(f"status={response.status}")
            print(response.read().decode("utf-8"))
            return 0
    except urllib.error.HTTPError as exc:
        print(f"status={exc.code}")
        print(exc.read().decode("utf-8"))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"request failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
