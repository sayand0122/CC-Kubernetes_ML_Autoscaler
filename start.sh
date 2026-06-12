#!/bin/bash
cd "$(dirname "$0")"

echo "========================================"
echo " ML Autoscaler — Starting Up"
echo "========================================"

# 1 - Start Minikube
echo ""
echo "▶ Starting Minikube..."
minikube start --cpus=20 --memory=10240

# 2 - Wait for Minikube to be fully ready
echo ""
echo "▶ Waiting for Minikube API to be ready..."
until kubectl cluster-info &>/dev/null; do
    echo "  ...not ready yet, waiting 5s"
    sleep 5
done
echo "✓ Minikube API ready"

# 3 - Enable metrics-server
echo ""
echo "▶ Enabling metrics-server..."
minikube addons enable metrics-server

# 4 - Load images
echo ""
echo "▶ Loading Docker images into Minikube..."
minikube image load ml-inference:latest
minikube image load dispatcher:latest
minikube image load monitoring:latest
minikube image load autoscaler:latest
echo "✓ Images loaded"

# 5 - Deploy everything
echo ""
echo "▶ Deploying to Kubernetes..."
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/ml-service.yaml
kubectl apply -f k8s/components.yaml

# 6 - Wait for pods
echo ""
echo "▶ Waiting for all pods to be ready..."
kubectl rollout status deployment/ml-service --timeout=120s
kubectl rollout status deployment/dispatcher --timeout=120s
kubectl rollout status deployment/monitoring --timeout=120s
kubectl rollout status deployment/autoscaler --timeout=120s

# 7 - Set URLs
export DISPATCHER_URL="http://$(minikube ip):$(kubectl get svc dispatcher -o jsonpath='{.spec.ports[0].nodePort}')"
export MONITORING_URL="http://$(minikube ip):$(kubectl get svc monitoring -o jsonpath='{.spec.ports[0].nodePort}')"

echo ""
echo "========================================"
echo " All pods running!"
echo " Dispatcher: $DISPATCHER_URL"
echo " Monitoring:  $MONITORING_URL"
echo "========================================"

# 8 - Run all experiments
echo ""
echo "▶ Running all experiments (~33 mins)..."
python scripts/run_experiment.py --all

# 9 - Plot results
echo ""
echo "▶ Plotting results..."
python scripts/plot_results.py

echo ""
echo "========================================"
echo " Done! Results saved to results/figures/"
echo "========================================"
