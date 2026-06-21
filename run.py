"""
Load Tester

This script replays a workload trace against the dispatcher service.
Each line in the `workload.txt` file represents the number of requests to send in one second.
It is intended for load generation and latency measurement during scaling experiments.

Usage:
  python run.py --dispatcher-url http://192.168.49.2:30906
  python run.py --dispatcher-url http://192.168.49.2:30906 --workload-file workload.txt
"""

import os
import glob
import time
import argparse
import threading
import requests
import numpy as np


def load_workload(path: str) -> list[int]:
    """Read a workload file and return one integer per second.

    The file contains whitespace-separated QPS values.
    """
    with open(path) as f:
        return [int(x) for x in f.read().split()]


def get_images(image_dir: str) -> list[str]:
    """Collect available image files for the load test."""
    images = (glob.glob(os.path.join(image_dir, "*.jpg")) +
              glob.glob(os.path.join(image_dir, "*.JPEG")) +
              glob.glob(os.path.join(image_dir, "*.jpeg")) +
              glob.glob(os.path.join(image_dir, "*.png")))
    if not images:
        raise FileNotFoundError(f"No images found in {image_dir}")
    return images


def send_request(url: str, image_path: str, results: dict, lock: threading.Lock):
    """Send a single image request to the dispatcher and record latency.

    Uses a shared results dictionary protected by a lock because requests are sent in parallel threads.
    """
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


def run_workload(dispatcher_url: str, image_dir: str, workload: list[int]):
    """Replay the workload one second at a time and print aggregate stats."""
    images  = get_images(image_dir)
    url     = dispatcher_url.rstrip("/") + "/predict"
    results = {"ok": 0, "err": 0, "latencies": []}
    lock    = threading.Lock()
    img_idx = 0

    total = len(workload)
    print(f"Workload: {total}s | max={max(workload)} qps | avg={sum(workload)/total:.1f} qps")
    print(f"Images:   {len(images)} found in {image_dir}")
    print(f"Sending to: {url}")
    print("")

    for second, qps in enumerate(workload):
        t_start = time.time()

        # Send up to `qps` requests spread evenly during this second.
        # Each request is executed in a separate daemon thread.
        if qps > 0:
            interval = 1.0 / qps
            for _ in range(qps):
                img = images[img_idx % len(images)]
                img_idx += 1
                t = threading.Thread(
                    target=send_request,
                    args=(url, img, results, lock),
                    daemon=True,
                )
                t.start()
                time.sleep(interval)

        # Print progress every 10 seconds
        if second % 10 == 0:
            with lock:
                lats = results["latencies"]
                if lats:
                    p99  = np.percentile(lats, 99)
                    mean = np.mean(lats)
                    print(f"  t={second:4d}s | qps={qps:2d} | "
                          f"ok={results['ok']} err={results['err']} | "
                          f"p99={p99*1000:.0f}ms mean={mean*1000:.0f}ms")
                else:
                    print(f"  t={second:4d}s | qps={qps:2d} | waiting for responses...")

        # Sleep for remainder of this second
        elapsed = time.time() - t_start
        time.sleep(max(0, 1.0 - elapsed))

    # Wait for in-flight requests to finish before computing final statistics.
    time.sleep(3)

    # Final stats
    with lock:
        lats = results["latencies"]
    print("")
    print("=== Final Results ===")
    print(f"  OK:   {results['ok']}")
    print(f"  ERR:  {results['err']}")
    if lats:
        print(f"  p50:  {np.percentile(lats, 50)*1000:.0f}ms")
        print(f"  p99:  {np.percentile(lats, 99)*1000:.0f}ms")
        print(f"  mean: {np.mean(lats)*1000:.0f}ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ML Inference Load Tester")
    parser.add_argument("--dispatcher-url", default="http://localhost:8081")
    parser.add_argument("--image-dir",      default="load_tester/images")
    parser.add_argument("--workload-file",  default="workload.txt")
    args = parser.parse_args()

    workload = load_workload(args.workload_file)
    run_workload(args.dispatcher_url, args.image_dir, workload)
