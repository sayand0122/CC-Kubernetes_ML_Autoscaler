"""
Experiment Runner

This script automates experiment execution for the custom autoscaler and HPA baselines.
It applies the selected scaling policy, runs the workload, gathers metrics, and writes per-second CSV output.
"""

import os
import csv
import time
import argparse
import subprocess
import requests
import threading
import glob
import numpy as np
from datetime import datetime

MONITORING_URL  = os.environ.get("MONITORING_URL", "http://localhost:8082")
DISPATCHER_URL  = os.environ.get("DISPATCHER_URL", "http://localhost:8081")
IMAGE_DIR       = "load_tester/images"
WORKLOAD_FILE   = "workload.txt"
RESULTS_DIR     = "results"
WARMUP          = 15


def kubectl(*args):
    """Run a kubectl command and print it for visibility."""
    cmd = ["kubectl"] + list(args)
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def wait_for_deployment(name="ml-service", timeout=120):
    print(f"  Waiting for {name}...")
    subprocess.run(["kubectl", "rollout", "status",
                    f"deployment/{name}", f"--timeout={timeout}s"], check=True)


def reset_replicas(n=1):
    """Return the ML service to a known starting replica count."""
    kubectl("scale", "deployment/ml-service", f"--replicas={n}")
    time.sleep(5)


def disable_hpa():
    try:
        kubectl("delete", "hpa", "--all", "--ignore-not-found=true")
    except Exception:
        pass


def enable_hpa(cpu_target: int):
    disable_hpa()
    kubectl("autoscale", "deployment/ml-service",
            "--cpu-percent", str(cpu_target), "--min=1", "--max=10")


def enable_custom_autoscaler():
    """Enable the custom autoscaler deployment and disable HPA."""
    disable_hpa()
    kubectl("scale", "deployment/autoscaler", "--replicas=1")


def disable_custom_autoscaler():
    kubectl("scale", "deployment/autoscaler", "--replicas=0")


def load_workload() -> list:
    """Read the shared workload trace from disk.

    The workload is a whitespace-separated list of per-second QPS values.
    """
    with open(WORKLOAD_FILE) as f:
        return [int(x) for x in f.read().split()]


def get_images() -> list:
    """Collect all available test images used by the load generator."""
    images = (glob.glob(os.path.join(IMAGE_DIR, "*.jpg")) +
              glob.glob(os.path.join(IMAGE_DIR, "*.JPEG")) +
              glob.glob(os.path.join(IMAGE_DIR, "*.jpeg")) +
              glob.glob(os.path.join(IMAGE_DIR, "*.png")))
    if not images:
        raise FileNotFoundError(f"No images in {IMAGE_DIR}")
    return images


def send_request(url, image_path, results, lock):
    """Send a single image request to the dispatcher and record success/latency."""
    t0 = time.perf_counter()
    try:
        with open(image_path, "rb") as f:
            r = requests.post(url, files={"image": f}, timeout=10)
        latency = time.perf_counter() - t0
        with lock:
            if r.status_code == 200:
                results["ok"] += 1
            else:
                results["err"] += 1
            results["latencies"].append(latency)
    except Exception:
        with lock:
            results["err"] += 1


def get_monitoring_snapshot() -> dict:
    """Fetch the current monitoring snapshot from the monitoring service."""
    try:
        r = requests.get(MONITORING_URL + "/current", timeout=3)
        return r.json()
    except Exception:
        return {}


def run_load(workload: list, images: list, label: str) -> list:
    """Replay the workload against the dispatcher and collect per-second metrics."""
    url     = DISPATCHER_URL.rstrip("/") + "/predict"
    rows    = []
    img_idx = 0

    print(f"\n  Sending workload ({len(workload)}s, max={max(workload)} qps)...")
    print(f"  {'Time':>6} | {'QPS':>4} | {'OK':>4} | {'ERR':>3} | {'p99':>8} | {'Replicas':>8}")
    print(f"  {'-'*55}")

    for second, qps in enumerate(workload):
        t_start = time.time()

        # Per-second results only
        sec_results = {"ok": 0, "err": 0, "latencies": []}
        lock        = threading.Lock()

        if qps > 0:
            interval = 1.0 / qps
            threads  = []
            for i in range(qps):
                img = images[(img_idx + i) % len(images)]
                t   = threading.Thread(
                    target=send_request,
                    args=(url, img, sec_results, lock),
                    daemon=True,
                )
                threads.append(t)
                t.start()
                time.sleep(interval)
            for t in threads:
                t.join(timeout=5)

        img_idx += qps

        with lock:
            lats = list(sec_results["latencies"])

        p99      = float(np.percentile(lats, 99)) if lats else 0.0
        p50      = float(np.percentile(lats, 50)) if lats else 0.0
        mean     = float(np.mean(lats))            if lats else 0.0
        slo_vio  = int((np.array(lats) > 0.5).sum()) if lats else 0

        # Get monitoring snapshot
        snap     = get_monitoring_snapshot()
        replicas = snap.get("ready_replicas", 1)

        rows.append({
            "experiment":         label,
            "time_s":             second,
            "qps":                qps,
            "ok":                 sec_results["ok"],
            "err":                sec_results["err"],
            "p50":                round(p50,  4),
            "p99":                round(p99,  4),
            "mean":               round(mean, 4),
            "slo_violations":     slo_vio,
            "slo_rate":           round(slo_vio / len(lats), 4) if lats else 0,
            "ready_replicas":     replicas,
            "cpu_cores":          replicas,
        })

        # Print every second
        print(f"  t={second:4d}s | qps={qps:2d} | "
              f"ok={sec_results['ok']:2d} err={sec_results['err']:2d} | "
              f"p99={p99*1000:6.0f}ms | replicas={replicas}")

        elapsed = time.time() - t_start
        time.sleep(max(0, 1.0 - elapsed))

    return rows


def save_csv(rows: list, label: str) -> str:
    """Persist experiment rows to a timestamped CSV file."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(RESULTS_DIR, f"{label}_{ts}.csv")
    with open(outfile, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Saved: {outfile}")
    return outfile


def run_experiment(label: str, setup_fn) -> str:
    print(f"\n{'='*60}")
    print(f" EXPERIMENT: {label}")
    print(f"{'='*60}")

    reset_replicas(1)
    wait_for_deployment()
    setup_fn()

    print(f"\n  Warmup {WARMUP}s...")
    time.sleep(WARMUP)

    workload = load_workload()
    images   = get_images()
    rows     = run_load(workload, images, label)
    outfile  = save_csv(rows, label)

    print(f"\n  Experiment {label} complete.")
    return outfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--autoscaler", choices=["custom", "hpa"], default="custom")
    parser.add_argument("--cpu-target", type=int, default=70, choices=[70, 90])
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.all:
        run_experiment("custom_autoscaler", enable_custom_autoscaler)
        disable_custom_autoscaler()
        time.sleep(10)

        run_experiment("hpa_70", lambda: enable_hpa(70))
        disable_hpa()
        time.sleep(10)

        run_experiment("hpa_90", lambda: enable_hpa(90))
        disable_hpa()

        print("\n✓ All experiments done!")
        print("  Run: python scripts/plot_results.py")

    elif args.autoscaler == "custom":
        run_experiment("custom_autoscaler", enable_custom_autoscaler)
        disable_custom_autoscaler()
    else:
        run_experiment(f"hpa_{args.cpu_target}", lambda: enable_hpa(args.cpu_target))
        disable_hpa()


if __name__ == "__main__":
    main()
