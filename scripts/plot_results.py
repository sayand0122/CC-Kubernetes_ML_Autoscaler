"""
Plot Results + Export to Excel
Generates comparison figures and an Excel file with full time-series data.

Usage:
  python scripts/plot_results.py
"""

import os
import glob
import argparse
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

RESULTS_DIR = "results"
OUTPUT_DIR  = "results/figures"

LABEL_MAP = {
    "custom_autoscaler": "Custom Autoscaler",
    "hpa_70":            "HPA 70% CPU",
    "hpa_90":            "HPA 90% CPU",
}
COLORS = {
    "custom_autoscaler": "#1f77b4",
    "hpa_70":            "#ff7f0e",
    "hpa_90":            "#2ca02c",
}


def load_csvs(results_dir: str) -> dict:
    dfs = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.csv"))):
        df = pd.read_csv(path)
        if df.empty or "experiment" not in df.columns:
            continue
        label = df["experiment"].iloc[0]
        df["time_s"] = df["timestamp"] - df["timestamp"].iloc[0]
        dfs[label] = df
    return dfs


def plot_combined(dfs: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), sharex=True)

    for label, df in dfs.items():
        color = COLORS.get(label)
        name  = LABEL_MAP.get(label, label)

        if "p99" in df.columns:
            s = df["p99"].rolling(3, min_periods=1).mean()
            ax1.plot(df["time_s"], s, label=name, color=color, linewidth=2)

        if "ready_replicas" in df.columns:
            ax2.plot(df["time_s"], df["ready_replicas"],
                     label=name, color=color, linewidth=2)

    ax1.axhline(0.5, color="red", linestyle="--", linewidth=1.5, label="SLO (0.5s)")
    ax1.set_ylabel("p99 Latency (s)", fontsize=12)
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_title("Autoscaler Comparison: Latency & Replicas", fontsize=14, fontweight="bold")

    ax2.set_ylabel("Ready Replicas", fontsize=12)
    ax2.set_xlabel("Time (seconds)", fontsize=12)
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "comparison_combined.png")
    plt.savefig(out, dpi=150)
    print(f"Saved plot: {out}")
    plt.close()


def export_excel(dfs: dict):
    try:
        import openpyxl
    except ImportError:
        print("Installing openpyxl...")
        os.system("pip install openpyxl -q")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    outfile = os.path.join(RESULTS_DIR, "results_summary.xlsx")

    with pd.ExcelWriter(outfile, engine="openpyxl") as writer:

        # ── One sheet per experiment with full time-series ────────────────────
        for label, df in dfs.items():
            sheet = LABEL_MAP.get(label, label)[:31]

            # Build clean export dataframe
            cols = {
                "time_s":          "Time (s)",
                "p50":             "p50 Latency (s)",
                "p99":             "p99 Latency (s)",
                "mean":            "Mean Latency (s)",
                "count":           "Request Count",
                "slo_violations":  "SLO Violations",
                "slo_rate":        "SLO Violation Rate",
                "ready_replicas":  "Ready Replicas",
            }
            available = {k: v for k, v in cols.items() if k in df.columns}
            df_out = df[list(available.keys())].copy()
            df_out.columns = list(available.values())
            df_out["Time (s)"] = df_out["Time (s)"].round(1)
            df_out.to_excel(writer, sheet_name=sheet, index=False)

            # Auto-size columns
            ws = writer.sheets[sheet]
            for col in ws.columns:
                max_len = max(len(str(cell.value or "")) for cell in col) + 2
                ws.column_dimensions[col[0].column_letter].width = max_len

        # ── Summary sheet ─────────────────────────────────────────────────────
        summary = []
        for label, df in dfs.items():
            p99  = df["p99"].dropna()
            reps = df["ready_replicas"].dropna()
            summary.append({
                "Experiment":            LABEL_MAP.get(label, label),
                "Avg p99 Latency (s)":   round(float(p99.mean()), 3),
                "Max p99 Latency (s)":   round(float(p99.max()), 3),
                "Min p99 Latency (s)":   round(float(p99.min()), 3),
                "Total SLO Violations":  int(df["slo_violations"].sum()) if "slo_violations" in df else "-",
                "Max Replicas":          int(reps.max()),
                "Final Replicas":        int(reps.iloc[-1]),
                "Duration (s)":          round(float(df["time_s"].max()), 0),
            })

        df_summary = pd.DataFrame(summary)
        df_summary.to_excel(writer, sheet_name="Summary", index=False)

        ws = writer.sheets["Summary"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col) + 2
            ws.column_dimensions[col[0].column_letter].width = max_len

    print(f"Saved Excel: {outfile}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default=RESULTS_DIR)
    args = parser.parse_args()

    dfs = load_csvs(args.results_dir)
    if not dfs:
        print(f"No experiment CSVs found in {args.results_dir}")
        return

    print(f"Loaded experiments: {list(dfs.keys())}")
    plot_combined(dfs)
    export_excel(dfs)
    print("\nDone!")
    print(f"  Plot:  {OUTPUT_DIR}/comparison_combined.png")
    print(f"  Excel: {RESULTS_DIR}/results_summary.xlsx")


if __name__ == "__main__":
    main()