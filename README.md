# ML Inference Autoscaling on Kubernetes

A benchmark project demonstrating a ResNet18 image classification service on Kubernetes with a custom latency-aware autoscaler, a dispatcher layer, live monitoring, and workload experiments.

## Project Overview

This repository implements a full end-to-end autoscaling experiment platform that includes:

- `service/`: Flask-based ResNet18 image classifier service with Prometheus metrics.
- `dispatcher/`: HTTP forwarder and load balancer that records end-to-end latency.
- `autoscaler/`: Custom Kubernetes autoscaler that scales `ml-service` using latency observations.
- `monitoring/`: Background metrics collector for dispatcher + replica counts.
- `load_tester/`: Workload driver that sends bursty QPS patterns to the dispatcher.
- `scripts/`: Experiment runner and result plotting utilities.
- `k8s/`: Kubernetes manifests for service deployments, RBAC, and HPA reference.
- `frontend_bridge.py`: Simple browser UI that uploads images to the dispatcher.

## Architecture

```text
           ┌────────────────┐
           │  Load Tester   │
           └───────┬────────┘
                   │
                   ▼
            ┌──────────────┐
            │  Dispatcher  │
            │  (HTTP proxy) │
            └──────┬───────┘
                   │
                   ▼
            ┌──────────────┐
            │  ml-service  │
            │  (ResNet18)  │
            └──────────────┘
                   ▲
                   │
          ┌────────┴────────┐
          │   Autoscaler    │
          └────────┬────────┘
                   │
                   ▼
            Kubernetes API
                   │
                   ▼
            ┌──────────────┐
            │ Monitoring   │
            │  service     │
            └──────────────┘
```

## Goals

- Keep p99 latency below 0.5s for the image classifier.
- Compare custom autoscaling against Kubernetes HPA at 70% and 90% CPU utilization.
- Produce reproducible experiment results and visualizations.

## Folder Breakdown

- `service/`
  - `app.py`: Flask inference server using ResNet18 from `torchvision`.
  - `Dockerfile`: Builds a CPU-only inference image with pre-downloaded model weights.

- `dispatcher/`
  - `app.py`: Forwards `/predict` requests to the ML service and records end-to-end latency.
  - `Dockerfile`: Builds a small forwarder image with Prometheus metrics.

- `monitoring/`
  - `app.py`: Polls dispatcher stats and deployment replica counts.
  - `Dockerfile`: Builds the monitoring container.

- `autoscaler/`
  - `autoscaler.py`: Polls monitoring data and patches `ml-service` replica count.
  - `Dockerfile`: Base container for the custom autoscaler.

- `load_tester/`
  - `run.py`: Sends a workload trace to the dispatcher and reports latency statistics.
  - `images/`: Image assets used by the load tester.

- `k8s/`
  - `components.yaml`: Deployments and services for `dispatcher`, `monitoring`, and `autoscaler`.
  - `ml-service.yaml`: Deployment and service for the ResNet18 inference service.
  - `rbac.yaml`: RBAC roles and bindings for autoscaler and monitoring.
  - `hpa.yaml`: Reference HorizontalPodAutoscaler manifest for 70% CPU.

- `scripts/`
  - `run_experiment.py`: Automates custom autoscaler and HPA comparison experiments.
  - `plot_results.py`: Generates plots and Excel reports from experiment CSV output.

- `frontend_bridge.py`
  - Simple browser-backed Flask app that uploads images to the dispatcher from `index.html`.

## Prerequisites

The repo is designed for Linux/macOS with Minikube and Python 3.11+. Install:

- Docker
- Minikube
- kubectl
- Python 3.11

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Quick Setup

Use `setup.sh` to start Minikube, enable metrics, install Python dependencies, build images, and deploy Kubernetes resources.

```bash
./setup.sh
```

If you prefer manual setup, run:

```bash
minikube start --cpus=4 --memory=8192 --driver=docker
eval "$(minikube docker-env)"
python3 -m pip install -r requirements.txt

docker build -t ml-inference:latest ./service/
docker build -t dispatcher:latest ./dispatcher/
docker build -t monitoring:latest ./monitoring/
docker build -t autoscaler:latest ./autoscaler/
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/ml-service.yaml
kubectl apply -f k8s/components.yaml
kubectl rollout status deployment/ml-service --timeout=120s
```

## Running the System

### Start backend services

Run the backend stack in one terminal:

```bash
./start.sh
```

This script:
- starts Minikube
- enables `metrics-server`
- loads Docker images into Minikube
- deploys `ml-service`, `dispatcher`, `monitoring`, and `autoscaler`
- waits for deployments to become ready

### Start the frontend bridge

In a second terminal, run the browser-facing frontend bridge:

```bash
python3 frontend_bridge.py
```

Then open the local UI at:

```bash
http://localhost:5000
```

### Stop and cleanup

```bash
./stop.sh
```

This script:
- deletes active HPAs
- scales deployments down to zero
- stops Minikube

## Experiments

### Run a single experiment

```bash
python3 scripts/run_experiment.py --autoscaler custom
```

To compare against HPA:

```bash
python3 scripts/run_experiment.py --autoscaler hpa --cpu-target 70
python3 scripts/run_experiment.py --autoscaler hpa --cpu-target 90
```

### Run all experiments sequentially

```bash
python3 scripts/run_experiment.py --all
```

The experiment runner:
- resets `ml-service` to one replica
- enables either the custom autoscaler or HPA
- warms up the system for 15 seconds
- replays `workload.txt` against the dispatcher
- records per-second metrics into `results/*.csv`

## Plotting and Reporting

Generate comparison charts and Excel summary from the recorded CSV files:

```bash
python3 scripts/plot_results.py
```

Output includes:
- `results/figures/comparison_combined.png`
- `results/results_summary.xlsx`

## Load Tester

The load tester sends traffic according to the pattern in `workload.txt`.

```bash
python3 load_tester/run.py --dispatcher-url http://<NODE_IP>:<NODE_PORT>
```

It reads images from `load_tester/images` and prints p50/p99 latency statistics.

## Frontend Demo

Run the simple browser UI locally with:

```bash
DISPATCHER_URL=http://<NODE_IP>:<NODE_PORT> python3 frontend_bridge.py
```

Then open:

```bash
http://localhost:5000
```

The page uploads image files to `/classify`, which forwards them to the dispatcher.

## Kubernetes Resources

- `k8s/ml-service.yaml`: ML service deployment + ClusterIP service
- `k8s/components.yaml`: dispatcher, monitoring, and autoscaler deployments + NodePort services
- `k8s/rbac.yaml`: RBAC permissions for autoscaler and monitoring
- `k8s/hpa.yaml`: HPA reference manifest for 70% CPU

## Key Endpoints

| Service | Endpoint | Purpose |
|---|---|---|
| `ml-service` | `/predict` | Image classification API |
| `ml-service` | `/health` | Health probe |
| `ml-service` | `/metrics` | Prometheus metrics |
| `ml-service` | `/stats` | Local inference latency summary |
| `dispatcher` | `/predict` | Proxy to ml-service |
| `dispatcher` | `/stats` | E2E latency summary |
| `dispatcher` | `/metrics` | Prometheus metrics |
| `monitoring` | `/current` | Latest scraped system metrics |
| `monitoring` | `/history` | Time series metrics history |
| `frontend_bridge` | `/classify` | Browser upload proxy |

## Custom Autoscaler Behavior

The custom autoscaler uses latency signals from the monitoring service to scale `ml-service`:

- Aggressively scale up when p99 exceeds the SLO target.
- Moderately scale up when p99 crosses a warning threshold.
- Scale down only after a stable low-latency period and cooldown.

This is intended to react faster than CPU-based HPA by using request latency directly.

## Notes

- `requirements.txt` contains shared development dependencies.
- `service/Dockerfile` pre-downloads ResNet18 weights to reduce runtime startup.
- `dispatcher` and `monitoring` are exposed as NodePort services so host tools can reach them from the Minikube host.

## File Map

```
README.md
requirements.txt
setup.sh
start.sh
stop.sh
frontend_bridge.py
index.html
service/
dispatcher/
monitoring/
autoscaler/
load_tester/
k8s/
scripts/
results/
```

## Troubleshooting

- If `kubectl` cannot reach the cluster, confirm Minikube is running and `kubectl config current-context` is set.
- If the dispatcher returns timeouts, make sure the `ml-service` pods are healthy and `/health` passes.
- If load test images are missing, populate `load_tester/images` with JPEG/PNG files.
- Use `kubectl logs deployment/<name>` to inspect service container logs.

## Recommended Workflow

1. Run `./setup.sh`
2. Validate deployments with `kubectl get pods`
3. Run experiments with `python3 scripts/run_experiment.py --all`
4. Plot results with `python3 scripts/plot_results.py`
5. Use `./stop.sh` to clean up
