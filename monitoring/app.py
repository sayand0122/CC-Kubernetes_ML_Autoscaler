"""
Monitoring Tool
- Polls dispatcher /stats and Kubernetes metrics API every POLL_INTERVAL seconds
- Stores a time-series in memory (and optionally to CSV)
- Exposes GET /current  → latest snapshot
- Exposes GET /history  → full time-series (for plotting)
- Exposes GET /health
"""

import os
import csv
import time
import threading
import requests
from flask import Flask, jsonify
from kubernetes import client, config

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DISPATCHER_URL  = os.environ.get("DISPATCHER_URL", "http://dispatcher:8081")
POLL_INTERVAL   = float(os.environ.get("POLL_INTERVAL", "5"))       # seconds
HISTORY_FILE    = os.environ.get("HISTORY_FILE", "/data/metrics.csv")
NAMESPACE       = os.environ.get("NAMESPACE", "default")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "ml-service")

# ── State ─────────────────────────────────────────────────────────────────────
_history: list[dict] = []
_lock    = threading.Lock()

# ── K8s client ────────────────────────────────────────────────────────────────
def _load_k8s():
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

_load_k8s()
_apps_v1  = client.AppsV1Api()
_core_v1  = client.CoreV1Api()


def _get_replica_count() -> int:
    """Return the number of ready replicas for the target deployment."""
    try:
        dep = _apps_v1.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
        return dep.status.ready_replicas or 0
    except Exception:
        return -1


def _get_requested_replicas() -> int:
    """Return the target replica count configured on the K8s deployment."""
    try:
        dep = _apps_v1.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
        return dep.spec.replicas or 0
    except Exception:
        return -1


def _poll():
    """Background thread that polls dispatcher stats and Kubernetes replica counts.

    The collected data is kept in memory for HTTP queries and also appended to a CSV file.
    """
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    write_header = not os.path.exists(HISTORY_FILE)

    with open(HISTORY_FILE, "a", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp", "p50", "p99", "mean", "count",
                           "slo_violations", "slo_rate",
                           "ready_replicas", "requested_replicas"]
        )
        if write_header:
            writer.writeheader()

        while True:
            t0 = time.time()
            row = {"timestamp": t0}

            # Dispatcher stats
            try:
                r = requests.get(DISPATCHER_URL + "/stats", timeout=3)
                row.update(r.json())
            except Exception:
                row.update({"p50": None, "p99": None, "mean": None,
                            "count": None, "slo_violations": None, "slo_rate": None})

            # K8s replica counts
            row["ready_replicas"]     = _get_replica_count()
            row["requested_replicas"] = _get_requested_replicas()

            with _lock:
                _history.append(row)

            writer.writerow(row)
            f.flush()

            elapsed = time.time() - t0
            time.sleep(max(0, POLL_INTERVAL - elapsed))


# Start background thread
_thread = threading.Thread(target=_poll, daemon=True)
_thread.start()


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/current")
def current():
    with _lock:
        latest = _history[-1] if _history else {}
    return jsonify(latest)


@app.route("/history")
def history():
    with _lock:
        data = list(_history)
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082, threaded=True)
