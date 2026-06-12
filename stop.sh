#!/bin/bash
echo "========================================"
echo " ML Autoscaler — Shutting Down"
echo "========================================"

# 1 - Clean up any running HPA
echo ""
echo "▶ Removing any active HPA..."
kubectl delete hpa --all --ignore-not-found=true

# 2 - Scale down all deployments to 0
echo ""
echo "▶ Scaling down deployments..."
kubectl scale deployment/ml-service  --replicas=0
kubectl scale deployment/dispatcher  --replicas=0
kubectl scale deployment/monitoring  --replicas=0
kubectl scale deployment/autoscaler  --replicas=0
echo "✓ Deployments scaled down"

# 3 - Stop Minikube
echo ""
echo "▶ Stopping Minikube..."
minikube stop
echo "✓ Minikube stopped"

echo ""
echo "========================================"
echo " Shutdown complete. See you next time!"
echo "========================================"
