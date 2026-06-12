#!/usr/bin/env bash
# setup.sh — one-shot setup for the ml-autoscaler project
set -euo pipefail

echo "========================================"
echo " ML Autoscaler Project — Setup"
echo "========================================"

# ── 1. Check prerequisites ────────────────────────────────────────────────────
for cmd in docker kubectl minikube python3; do
    if ! command -v $cmd &>/dev/null; then
        echo "ERROR: '$cmd' not found. Please install it first."
        exit 1
    fi
done

echo "✓ Prerequisites found"

# ── 2. Start Minikube ─────────────────────────────────────────────────────────
echo ""
echo "Starting Minikube (4 CPUs, 8GB RAM) …"
minikube start --cpus=4 --memory=8192 --driver=docker 2>/dev/null || \
minikube start --cpus=4 --memory=8192

echo "✓ Minikube running"
minikube status

# Enable metrics-server (needed for HPA)
echo "Enabling metrics-server addon …"
minikube addons enable metrics-server

# ── 3. Point Docker to Minikube's daemon ──────────────────────────────────────
echo ""
echo "Switching to Minikube Docker daemon …"
eval "$(minikube docker-env)"

# ── 4. Install Python dependencies ───────────────────────────────────────────
echo ""
echo "Installing Python dependencies …"
pip install -r requirements.txt -q

# ── 5. Build Docker images ────────────────────────────────────────────────────
echo ""
echo "Building Docker images …"

docker build -t ml-inference:latest  ./service/
echo "✓ ml-inference:latest"

docker build -t dispatcher:latest    ./dispatcher/
echo "✓ dispatcher:latest"

docker build -t monitoring:latest    ./monitoring/
echo "✓ monitoring:latest"

docker build -t autoscaler:latest    ./autoscaler/
echo "✓ autoscaler:latest"

# ── 6. Deploy to Kubernetes ───────────────────────────────────────────────────
echo ""
echo "Deploying to Kubernetes …"

kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/ml-service.yaml
kubectl apply -f k8s/components.yaml

echo "Waiting for ml-service to be ready …"
kubectl rollout status deployment/ml-service --timeout=120s

echo ""
echo "========================================"
echo " Setup complete!"
echo "========================================"
echo ""
echo "Dispatcher NodePort:"
kubectl get svc dispatcher -o jsonpath='{.spec.ports[0].nodePort}'
echo ""
echo "Minikube IP: $(minikube ip)"
echo ""
echo "Next steps:"
echo "  1. Download images:  git clone https://github.com/EliSchwartz/imagenet-sample-images load_tester/images"
echo "  2. Run all experiments: python scripts/run_experiment.py --all"
echo "  3. Plot results:        python scripts/plot_results.py"
