# ML Inference Autoscaling on Kubernetes

ResNet18 image classification service with custom autoscaler on Minikube.

## Goal
- Server-side latency < 0.5s (p99)
- Custom autoscaler outperforms Kubernetes HPA (70% and 90% CPU targets)

## Architecture

```
Load Tester → Dispatcher → [Replica 1..N] ← Autoscaler ← Monitoring
                                                  ↕
                                            API Server (K8s)
```

## Components

| Folder | Description |
|---|---|
| `service/` | Flask + ResNet18 image classifier (Dockerized) |
| `dispatcher/` | Load balancer, forwards requests, tracks latency |
| `monitoring/` | Scrapes metrics from replicas + dispatcher |
| `autoscaler/` | Custom autoscaler using K8s API |
| `load_tester/` | Workload driver script |
| `k8s/` | All Kubernetes manifests |
| `scripts/` | Helper scripts (setup, run experiments, plot results) |

## Quick Start

### 1. Prerequisites
```bash
# Install Minikube
brew install minikube        # macOS
# or: https://minikube.sigs.k8s.io/docs/start/

# Install kubectl
brew install kubectl

# Install Python deps
pip install -r requirements.txt
```

### 2. Start Minikube
```bash
minikube start --cpus=4 --memory=8192
eval $(minikube docker-env)   # use minikube's Docker daemon
```

### 3. Build & Deploy the ML Service
```bash
cd service
docker build -t ml-inference:latest .
cd ..
kubectl apply -f k8s/
```

### 4. Run an Experiment
```bash
# With your custom autoscaler
python scripts/run_experiment.py --autoscaler custom

# With HPA at 70% CPU
python scripts/run_experiment.py --autoscaler hpa --cpu-target 70

# With HPA at 90% CPU
python scripts/run_experiment.py --autoscaler hpa --cpu-target 90
```

### 5. Plot Results
```bash
python scripts/plot_results.py
```

## Experiment Comparison
The final experiment compares:
1. **Custom Autoscaler** — your implementation
2. **HPA 70%** — Kubernetes HPA with 70% CPU target
3. **HPA 90%** — Kubernetes HPA with 90% CPU target

Metrics tracked:
- p99 latency over time
- Number of CPU cores / replicas over time
