"""
Experiment Runner
Runs 3 experiments sequentially and saves metric time-series to CSV:
  1. Custom autoscaler
  2. HPA at 70% CPU
  3. HPA at 90% CPU
"""

import os
import time
import argparse
import subprocess
import requests
import csv
from datetime import datetime

MONITORING_URL  = os.environ.get("MONITORING_URL", "http://localhost:8082")
DISPATCHER_URL  = os.environ.get("DISPATCHER_URL", "http://localhost:8081")
IMAGE_DIR       = "load_tester/images"
WORKLOAD_FILE   = "workload.txt"
RESULTS_DIR     = "results"
WARMUP          = 30   # seconds before recording


def kubectl(*args):
    cmd = ["kubectl"] + list(args)
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def wait_for_deployment(name="ml-service", timeout=120):
    print(f"Waiting for {name} to be ready …")
    subprocess.run(
        ["kubectl", "rollout", "status", f"deployment/{name}",
         f"--timeout={timeout}s"], check=True,
    )


def reset_replicas(n=1):
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
    disable_hpa()
    kubectl("scale", "deployment/autoscaler", "--replicas=1")


def disable_custom_autoscaler():
    kubectl("scale", "deployment/autoscaler", "--replicas=0")


def get_workload_duration() -> int:
    try:
        with open(WORKLOAD_FILE) as f:
            return len(f.read().split())
    except Exception:
        return 630


def stream_metrics(label: str, duration: int) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(RESULTS_DIR, f"{label}_{ts}.csv")
    t_end   = time.time() + duration
    rows    = []

    print(f"Recording metrics for {duration}s → {outfile}")
    while time.time() < t_end:
        try:
            r   = requests.get(MONITORING_URL + "/current", timeout=3)
            row = r.json()
            row["experiment"] = label
            rows.append(row)
        except Exception:
            pass
        time.sleep(5)

    if rows:
        with open(outfile, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Saved {len(rows)} rows to {outfile}")

    return outfile


def run_experiment(label: str, setup_fn):
    duration = get_workload_duration()

    print(f"\n{'='*60}")
    print(f"EXPERIMENT: {label}")
    print(f"{'='*60}")

    reset_replicas(1)
    wait_for_deployment()
    setup_fn()

    print(f"Warmup {WARMUP}s …")
    time.sleep(WARMUP)

    # Start load tester using workload.txt
    load_proc = subprocess.Popen([
        "python", "load_tester/run.py",
        "--dispatcher-url", DISPATCHER_URL,
        "--image-dir",      IMAGE_DIR,
        "--workload-file",  WORKLOAD_FILE,
    ])

    try:
        outfile = stream_metrics(label, duration + 10)
    finally:
        load_proc.wait()

    print(f"Experiment {label} complete → {outfile}")
    return outfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--autoscaler", choices=["custom", "hpa"], default="custom")
    parser.add_argument("--cpu-target", type=int, default=70, choices=[70, 90])
    parser.add_argument("--all", action="store_true",
                        help="Run all 3 experiments sequentially")
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

        print("\nAll experiments done. Run: python scripts/plot_results.py")

    elif args.autoscaler == "custom":
        run_experiment("custom_autoscaler", enable_custom_autoscaler)
        disable_custom_autoscaler()
    else:
        run_experiment(f"hpa_{args.cpu_target}", lambda: enable_hpa(args.cpu_target))
        disable_hpa()


if __name__ == "__main__":
    main()
