"""
Image Classification Service
- Accepts POST /predict with an image file
- Returns top-5 labels using ResNet18
- Exposes GET /metrics for Prometheus scraping
- Exposes GET /health for liveness probe
"""

import time
import io
import threading
from collections import deque

import torch
import torchvision.transforms as transforms
from torchvision.models import resnet18, ResNet18_Weights
from flask import Flask, request, jsonify
from PIL import Image
from prometheus_client import Histogram, Counter, generate_latest, CONTENT_TYPE_LATEST

app = Flask(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_LATENCY = Histogram(
    "inference_latency_seconds",
    "Per-request inference latency",
    buckets=[0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 2.0],
)
REQUEST_COUNT = Counter("inference_requests_total", "Total inference requests")
ERROR_COUNT   = Counter("inference_errors_total",   "Total inference errors")

# ── Model (loaded once at startup) ───────────────────────────────────────────
print("Loading ResNet18 …")
weights      = ResNet18_Weights.IMAGENET1K_V1
model        = resnet18(weights=weights)
model.eval()
preprocessor = weights.transforms()
categories   = weights.meta["categories"]
print("Model ready.")

# ── In-memory latency ring buffer (last 1000 requests) ───────────────────────
_latencies: deque = deque(maxlen=1000)
_lat_lock = threading.Lock()


def _preprocess(file_bytes: bytes) -> torch.Tensor:
    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    return preprocessor(img).unsqueeze(0)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/predict", methods=["POST"])
def predict():
    t0 = time.perf_counter()
    REQUEST_COUNT.inc()

    if "image" not in request.files:
        ERROR_COUNT.inc()
        return jsonify({"error": "No image field in request"}), 400

    try:
        img_bytes = request.files["image"].read()
        inp = _preprocess(img_bytes)

        with torch.no_grad():
            preds = model(inp).squeeze(0)

        top5_idx    = preds.argsort(descending=True)[:5].tolist()
        top5_labels = [categories[i] for i in top5_idx]
        top5_scores = preds.softmax(0)[top5_idx].tolist()

        latency = time.perf_counter() - t0
        REQUEST_LATENCY.observe(latency)
        with _lat_lock:
            _latencies.append(latency)

        return jsonify({"labels": top5_labels, "scores": top5_scores, "latency_s": latency})

    except Exception as exc:
        ERROR_COUNT.inc()
        return jsonify({"error": str(exc)}), 500


@app.route("/metrics")
def metrics():
    """Prometheus-compatible metrics endpoint."""
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/stats")
def stats():
    """Quick JSON stats used by the custom monitoring tool."""
    with _lat_lock:
        lats = list(_latencies)

    if not lats:
        return jsonify({"p50": 0, "p99": 0, "count": 0})

    import numpy as np
    return jsonify({
        "p50":   float(np.percentile(lats, 50)),
        "p99":   float(np.percentile(lats, 99)),
        "mean":  float(np.mean(lats)),
        "count": len(lats),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
