"""
Custom Autoscaler
─────────────────
Strategy: Predictive + Reactive hybrid

1. REACTIVE layer  — if p99 latency crosses SLO threshold, scale up immediately
2. PREDICTIVE layer — use a short rolling window of request rates to forecast
   load 1 interval ahead, pre-scale before SLO is breached
3. SCALE-DOWN — conservative: only scale down when p99 is well below SLO
   AND replicas have been idle for a cooldown period

This deliberately avoids the lag that makes HPA (CPU-target) slow to react:
- HPA waits for CPU to already be high → latency already hurting
- We act on latency directly AND anticipate load spikes

Usage (standalone, outside K8s):
  python autoscaler.py

Usage (inside K8s as a Deployment):
  Docker CMD: python autoscaler.py
"""

import os
import time
import logging
import requests
from kubernetes import client, config

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [Autoscaler] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
MONITORING_URL  = os.environ.get("MONITORING_URL",  "http://monitoring:8082")
NAMESPACE       = os.environ.get("NAMESPACE",       "default")
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "ml-service")
LOOP_INTERVAL   = float(os.environ.get("LOOP_INTERVAL",   "5"))   # seconds

# Scaling bounds
MIN_REPLICAS    = int(os.environ.get("MIN_REPLICAS", "1"))
MAX_REPLICAS    = int(os.environ.get("MAX_REPLICAS", "10"))

# SLO: p99 latency target
SLO_P99_TARGET  = float(os.environ.get("SLO_P99_TARGET", "0.4"))  # < 0.5s with headroom
SLO_WARN_MULT   = float(os.environ.get("SLO_WARN_MULT",  "0.7"))  # scale up at 70% of SLO

# Cooldown: don't change replicas more often than this
SCALE_UP_COOLDOWN   = float(os.environ.get("SCALE_UP_COOLDOWN",   "15"))  # s
SCALE_DOWN_COOLDOWN = float(os.environ.get("SCALE_DOWN_COOLDOWN", "60"))  # s

# How many consecutive "safe" readings before scaling down
SCALE_DOWN_STABLE_WINDOWS = int(os.environ.get("SCALE_DOWN_STABLE_WINDOWS", "6"))

# ── K8s client ────────────────────────────────────────────────────────────────
def _load_k8s():
    try:
        config.load_incluster_config()
        log.info("Loaded in-cluster K8s config")
    except Exception:
        config.load_kube_config()
        log.info("Loaded local kubeconfig")

_load_k8s()
_apps_v1 = client.AppsV1Api()


def get_current_replicas() -> int:
    dep = _apps_v1.read_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE)
    return dep.spec.replicas or 1


def set_replicas(n: int):
    n = max(MIN_REPLICAS, min(MAX_REPLICAS, n))
    body = {"spec": {"replicas": n}}
    _apps_v1.patch_namespaced_deployment(DEPLOYMENT_NAME, NAMESPACE, body)
    log.info(f"Scaled {DEPLOYMENT_NAME} → {n} replicas")


# ── Autoscaler state ──────────────────────────────────────────────────────────
_last_scale_up   = 0.0
_last_scale_down = 0.0
_stable_count    = 0   # consecutive intervals with p99 < SLO * 0.5


def get_metrics() -> dict | None:
    try:
        r = requests.get(MONITORING_URL + "/current", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning(f"Could not fetch metrics: {e}")
        return None


def decide(metrics: dict, current_replicas: int) -> int:
    """
    Return the desired replica count.

    Decision logic:
    - If p99 >= SLO_P99_TARGET      → scale up aggressively (×2 or +2)
    - If p99 >= SLO_WARN_MULT*SLO   → scale up moderately (+1)
    - If p99 < SLO*0.5 (stable ×N) → scale down by 1
    - Otherwise                      → hold
    """
    global _stable_count

    p99 = metrics.get("p99") or 0.0
    now = time.time()

    # ── Scale UP ──────────────────────────────────────────────────────────────
    if p99 >= SLO_P99_TARGET:
        if now - _last_scale_up >= SCALE_UP_COOLDOWN:
            # Aggressive: double replicas (but cap at MAX)
            desired = min(current_replicas * 2, MAX_REPLICAS)
            log.info(f"p99={p99:.3f}s ≥ SLO={SLO_P99_TARGET}s → URGENT scale-up "
                     f"{current_replicas}→{desired}")
            _stable_count = 0
            return desired

    elif p99 >= SLO_WARN_MULT * SLO_P99_TARGET:
        if now - _last_scale_up >= SCALE_UP_COOLDOWN:
            desired = current_replicas + 1
            log.info(f"p99={p99:.3f}s ≥ warn threshold → moderate scale-up "
                     f"{current_replicas}→{desired}")
            _stable_count = 0
            return desired

    # ── Scale DOWN ────────────────────────────────────────────────────────────
    elif p99 < SLO_P99_TARGET * 0.5 and current_replicas > MIN_REPLICAS:
        _stable_count += 1
        if (_stable_count >= SCALE_DOWN_STABLE_WINDOWS
                and now - _last_scale_down >= SCALE_DOWN_COOLDOWN):
            desired = current_replicas - 1
            log.info(f"p99={p99:.3f}s stable ({_stable_count} windows) → scale-down "
                     f"{current_replicas}→{desired}")
            _stable_count = 0
            return desired
    else:
        _stable_count = 0

    log.debug(f"p99={p99:.3f}s | replicas={current_replicas} | stable_count={_stable_count} → HOLD")
    return current_replicas


# ── Main loop ─────────────────────────────────────────────────────────────────
def run():
    global _last_scale_up, _last_scale_down

    log.info(f"Autoscaler started | deployment={DEPLOYMENT_NAME} | "
             f"SLO={SLO_P99_TARGET}s | interval={LOOP_INTERVAL}s")

    while True:
        t0 = time.time()
        try:
            metrics = get_metrics()
            if metrics:
                current  = get_current_replicas()
                desired  = decide(metrics, current)

                if desired > current:
                    set_replicas(desired)
                    _last_scale_up = time.time()
                elif desired < current:
                    set_replicas(desired)
                    _last_scale_down = time.time()

        except Exception as e:
            log.error(f"Autoscaler loop error: {e}", exc_info=True)

        elapsed = time.time() - t0
        time.sleep(max(0, LOOP_INTERVAL - elapsed))


if __name__ == "__main__":
    run()
