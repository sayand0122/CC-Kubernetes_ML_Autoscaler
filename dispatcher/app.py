"""
Dispatcher
- Discovers ML service replicas from Kubernetes (via env or config)
- Round-robin load balances POST /predict requests
- Tracks end-to-end latency per request
- Exposes GET /metrics (Prometheus) and GET /stats (JSON)
- Exposes GET /health
"""

import os
import time
import threading
import requests
import numpy as np
from collections import deque
from flask import Flask, request, jsonify
from prometheus_client import Histogram, Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
# Comma-separated list of backend URLs, e.g. "http://ml-service:8080"
# When running in K8s, we use the Service DNS name; replicas are behind it.
BACKEND_URL  = os.environ.get("BACKEND_URL", "http://ml-service:8080")
PREDICT_PATH = "/predict"
STATS_PATH   = "/stats"

# ── Prometheus metrics ────────────────────────────────────────────────────────
E2E_LATENCY  = Histogram("dispatcher_e2e_latency_seconds", "End-to-end latency",
                         buckets=[0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0, 5.0])
TOTAL_REQ    = Counter("dispatcher_requests_total",  "Total forwarded requests")
FAILED_REQ   = Counter("dispatcher_failed_total",    "Failed / timed-out requests")
ACTIVE_REQ   = Gauge("dispatcher_active_requests",   "Requests in-flight")

# ── In-memory latency store (rolling 10-min window) ───────────────────────────
_window_secs = 600
_records: deque = deque()   # stores tuples of (timestamp, latency_s)
_lock = threading.Lock()


def _record_latency(lat: float):
    """Append a latency sample and trim old samples from the sliding window."""
    now = time.time()
    with _lock:
        _records.append((now, lat))
        cutoff = now - _window_secs
        while _records and _records[0][0] < cutoff:
            _records.popleft()


def _get_stats() -> dict:
    """Compute latency summary statistics for the recent sliding window."""
    now = time.time()
    with _lock:
        cutoff = now - _window_secs
        lats = [l for ts, l in _records if ts >= cutoff]
    if not lats:
        return {"p50": 0.0, "p99": 0.0, "mean": 0.0, "count": 0,
                "slo_violations": 0, "slo_rate": 0.0}
    arr = np.array(lats)
    violations = int((arr > 0.5).sum())
    return {
        "p50":            float(np.percentile(arr, 50)),
        "p99":            float(np.percentile(arr, 99)),
        "mean":           float(arr.mean()),
        "count":          len(arr),
        "slo_violations": violations,
        "slo_rate":       violations / len(arr),
    }


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/predict", methods=["POST"])
def predict():
    TOTAL_REQ.inc()
    ACTIVE_REQ.inc()
    t0 = time.perf_counter()

    try:
        if "image" not in request.files:
            return jsonify({"error": "No image field"}), 400

        img_bytes = request.files["image"].read()
        files = {"image": ("image.jpg", img_bytes, "image/jpeg")}

        resp = requests.post(
            BACKEND_URL + PREDICT_PATH,
            files=files,
            timeout=10,
        )
        resp.raise_for_status()

        latency = time.perf_counter() - t0
        E2E_LATENCY.observe(latency)
        _record_latency(latency)

        data = resp.json()
        data["dispatcher_latency_s"] = latency
        return jsonify(data), resp.status_code

    except requests.exceptions.Timeout:
        FAILED_REQ.inc()
        latency = time.perf_counter() - t0
        _record_latency(latency)
        return jsonify({"error": "Backend timeout"}), 504

    except Exception as exc:
        FAILED_REQ.inc()
        return jsonify({"error": str(exc)}), 502

    finally:
        ACTIVE_REQ.dec()


@app.route("/stats")
def stats():
    return jsonify(_get_stats())


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081, threaded=True)
