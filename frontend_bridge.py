"""
Frontend Bridge

A minimal Flask app that serves the browser UI and forwards uploaded images to the dispatcher.
This allows the UI to stay local while the classifier and dispatcher run in Minikube.
"""

import os
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Dispatcher service URL used by the frontend proxy.
# Override with DISPATCHER_URL in the environment when needed.
DISPATCHER_URL = os.environ.get("DISPATCHER_URL", "http://192.168.49.2:32607")

# Serve the frontend
@app.route("/")
def index():
    """Serve the static frontend HTML page from the repository root."""
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))


@app.route("/classify", methods=["POST", "OPTIONS"])
def classify():
    """Receive a frontend upload and proxy it to the dispatcher service."""
    if request.method == "OPTIONS":
        return "", 200

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file      = request.files["file"]
    img_bytes = file.read()

    try:
        # Forward the uploaded image bytes to the dispatcher prediction endpoint.
        resp = requests.post(
            DISPATCHER_URL + "/predict",
            files={"image": (file.filename, img_bytes, file.content_type)},
            timeout=10,
        )
        resp.raise_for_status()
        data    = resp.json()
        labels  = data.get("labels", [])
        scores  = data.get("scores", [])
        latency = data.get("latency_s", 0)

        return jsonify({
            "predictions": [
                {"label": l, "confidence": s}
                for l, s in zip(labels, scores)
            ],
            "latency_s":            latency,
            "dispatcher_latency_s": data.get("dispatcher_latency_s", 0),
        })

    except requests.exceptions.Timeout:
        return jsonify({"error": "Backend timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print(f"Open in browser: http://localhost:5000")
    print(f"Forwarding to:   {DISPATCHER_URL}")
    app.run(host="0.0.0.0", port=5000, debug=False)
