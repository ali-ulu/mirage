"""
Test & demonstration script for MIRAGE synthetic data engine.

Validates:
  1. Performance constraint: ms_per_row <= 0.05 for 10,000 rows.
  2. Statistical isomorphism: mean, std, and correlation matrix of numeric
     columns are preserved within tolerance.
  3. Schema preservation: column types and formats match the original.
  4. Categorical / free-text / timestamp / formatted columns produce
     plausible, format-preserving outputs.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Make sure we can import the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mirage import MirageSynthesizer


# ---------------------------------------------------------------------------
# Build a realistic real-data sample
# ---------------------------------------------------------------------------
def build_real_data(n: int = 2_000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Correlated numeric columns
    # age ~ N(35, 10), salary correlated with age + noise, score anti-correlated
    age = rng.normal(35, 10, n).clip(18, 75)
    salary = age * 2500 + rng.normal(0, 8000, n) + 15000
    salary = salary.clip(20000, 250000)
    # score anti-correlated with salary (slightly)
    score = 100 - (salary - 50000) / 5000 + rng.normal(0, 5, n)
    score = score.clip(0, 100)
    sessions = rng.poisson(lam=np.maximum(1, age / 10)).astype(int)

    # Categorical: department
    departments = ["Engineering", "Sales", "Marketing", "Finance", "HR", "Legal"]
    dept = rng.choice(departments, n, p=[0.35, 0.20, 0.15, 0.15, 0.10, 0.05])

    # Formatted: email
    names = ["john", "alice", "bob", "carol", "dave", "eve", "frank", "grace"]
    email = np.array(
        [f"{rng.choice(names)}.{rng.integers(1, 9999)}@example.com" for _ in range(n)]
    )

    # Formatted: UUID (as string)
    import uuid as uuidlib
    user_id = np.array([str(uuidlib.uuid4()) for _ in range(n)])

    # Timestamp (last 2 years, log-distributed)
    base = pd.Timestamp("2024-01-01")
    ts = pd.to_datetime(
        base.value + rng.lognormal(mean=20, sigma=1.5, size=n) % (365 * 24 * 3600 * 1e9),
        unit="ns",
    )
    # Format as ISO8601 strings
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ").to_numpy()

    # Free text (titles) — high cardinality
    titles_pool = [
        "Quarterly Business Review",
        "Annual Security Audit Report",
        "Q3 Performance Dashboard",
        "Customer Engagement Metrics",
        "Incident Response Plan v2",
        "Vendor Risk Assessment Summary",
        "Financial Forecast 2025",
        "Engineering Sprint Retrospective",
        "Data Migration Runbook",
        "Compliance Gap Analysis",
    ]
    # Add some structure: prefix + suffix to give Markov something to learn
    titles = np.array(
        [
            f"{rng.choice(titles_pool)} - {rng.choice(['Draft', 'Final', 'Revised', 'Internal'])}"
            for _ in range(n)
        ]
    )

    # Numeric with some NaNs
    bonus = rng.normal(5000, 2000, n)
    bonus[rng.random(n) < 0.15] = np.nan

    return pd.DataFrame(
        {
            "user_id": user_id,
            "age": age.astype(int),
            "salary": salary.round(2),
            "score": score.round(2),
            "sessions": sessions,
            "department": dept,
            "email": email,
            "created_at": ts_str,
            "title": titles,
            "bonus": bonus,
        }
    )


# ---------------------------------------------------------------------------
# Statistical isomorphism validation
# ---------------------------------------------------------------------------
def validate_numeric_stats(real: pd.DataFrame, synth: pd.DataFrame, cols: list[str]) -> dict:
    """Compare mean, std, and correlation matrix of numeric columns."""
    report = {}
    for col in cols:
        r = real[col].dropna()
        s = synth[col].dropna()
        report[col] = {
            "real_mean": float(r.mean()),
            "synth_mean": float(s.mean()),
            "mean_diff_pct": abs(r.mean() - s.mean()) / (abs(r.mean()) + 1e-9) * 100,
            "real_std": float(r.std()),
            "synth_std": float(s.std()),
            "std_diff_pct": abs(r.std() - s.std()) / (r.std() + 1e-9) * 100,
        }
    # Correlation matrix comparison (Frobenius norm of difference)
    if len(cols) >= 2:
        corr_r = real[cols].corr().to_numpy()
        corr_s = synth[cols].corr().to_numpy()
        frob = float(np.linalg.norm(corr_r - corr_s, ord="fro"))
        report["_correlation_frobenius_diff"] = frob
        report["_correlation_real"] = corr_r.tolist()
        report["_correlation_synth"] = corr_s.tolist()
    return report


def main():
    print("=" * 70)
    print("MIRAGE — Task 01 Validation")
    print("=" * 70)

    # 1. Build real data
    print("\n[1] Building real data sample (2,000 rows)...")
    real_df = build_real_data(n=2_000, seed=42)
    print(f"    Shape: {real_df.shape}")
    print(f"    Columns: {list(real_df.columns)}")
    print(f"    Types:\n{real_df.dtypes.to_string()}")

    # 2. Fit synthesizer
    print("\n[2] Fitting synthesizer...")
    t0 = time.perf_counter()
    synth_engine = MirageSynthesizer(seed=123).fit(real_df)
    fit_ms = (time.perf_counter() - t0) * 1000
    print(f"    Fit time: {fit_ms:.1f} ms")
    print(f"    Numeric block: {[synth_engine.column_order[i] for i in synth_engine.numeric_indices]}")
    print(f"    Column profiles:")
    for p in synth_engine.profiles:
        extra = ""
        if p.col_type == "categorical":
            extra = f" (cats={len(p.categories)})"
        elif p.col_type == "formatted":
            extra = f" (kind={p.format_kind})"
        elif p.col_type == "free_text":
            extra = f" (markov_states={len(p.markov_table['trans'])})"
        print(f"      - {p.name:12s} -> {p.col_type}{extra}  null={p.null_prob:.2f}")

    # 3. Generate 10,000 synthetic rows (the WBS target)
    print("\n[3] Generating 10,000 synthetic rows...")
    result = synth_engine.synthesize(10_000)
    print(f"    Elapsed:    {result.elapsed_ms:.1f} ms")
    print(f"    Per row:    {result.ms_per_row:.5f} ms")
    print(f"    Throughput: {result.rows_per_ms:.1f} rows/ms  ({result.rows_per_ms*1000:.0f} rows/sec)")
    print(f"    Budget:     0.05000 ms/row")
    print(f"    WITHIN BUDGET: {result.ms_per_row <= 0.05}")

    # 4. Show a sample of synthetic data
    print("\n[4] Sample synthetic rows (first 5):")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 180)
    print(result.df.head(5).to_string())

    # 5. Validate statistical isomorphism
    print("\n[5] Statistical isomorphism validation:")
    numeric_cols = [synth_engine.column_order[i] for i in synth_engine.numeric_indices]
    report = validate_numeric_stats(real_df, result.df, numeric_cols)

    print("\n    Per-column statistics:")
    print(f"    {'Column':12s} {'μ(real)':>12s} {'μ(synth)':>12s} {'Δμ%':>7s}   {'σ(real)':>10s} {'σ(synth)':>10s} {'Δσ%':>7s}")
    for col in numeric_cols:
        r = report[col]
        print(
            f"    {col:12s} {r['real_mean']:12.2f} {r['synth_mean']:12.2f} {r['mean_diff_pct']:6.2f}%   "
            f"{r['real_std']:10.2f} {r['synth_std']:10.2f} {r['std_diff_pct']:6.2f}%"
        )
    print(f"\n    Correlation matrix Frobenius diff: {report['_correlation_frobenius_diff']:.4f}")
    print("    (lower = better; ~0.05 is excellent for n=10k)")
    print("\n    Real correlation matrix:")
    for row in report["_correlation_real"]:
        print("      " + "  ".join(f"{v:+.3f}" for v in row))
    print("    Synth correlation matrix:")
    for row in report["_correlation_synth"]:
        print("      " + "  ".join(f"{v:+.3f}" for v in row))

    # 6. Schema preservation spot-check
    print("\n[6] Schema preservation spot-check:")
    sample_email = result.df["email"].dropna().head(3).tolist()
    sample_uuid = result.df["user_id"].dropna().head(3).tolist()
    sample_ts = result.df["created_at"].dropna().head(3).tolist()
    print(f"    Emails:  {sample_email}")
    print(f"    UUIDs:   {sample_uuid}")
    print(f"    Timestamps: {sample_ts}")

    # 7. Performance stress test: 100k rows
    print("\n[7] Stress test: 100,000 rows...")
    result_big = synth_engine.synthesize(100_000)
    print(f"    Elapsed: {result_big.elapsed_ms:.1f} ms")
    print(f"    Per row: {result_big.ms_per_row:.5f} ms")
    print(f"    WITHIN BUDGET: {result_big.ms_per_row <= 0.05}")

    # 8. Save sample output
    output_path = Path("/home/z/my-project/download/mirage_synthetic_sample.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.df.to_csv(output_path, index=False)
    print(f"\n[8] Sample CSV saved: {output_path}")

    print("\n" + "=" * 70)
    print("Validation complete.")
    print("=" * 70)

    # Final pass/fail summary
    pass_perf = result.ms_per_row <= 0.05
    pass_mean = all(report[c]["mean_diff_pct"] < 5.0 for c in numeric_cols)
    pass_std = all(report[c]["std_diff_pct"] < 10.0 for c in numeric_cols)
    pass_corr = report["_correlation_frobenius_diff"] < 0.10
    print(f"\nFINAL: performance={'PASS' if pass_perf else 'FAIL'} | "
          f"mean={'PASS' if pass_mean else 'FAIL'} | "
          f"std={'PASS' if pass_std else 'FAIL'} | "
          f"correlation={'PASS' if pass_corr else 'FAIL'}")

    return 0 if all([pass_perf, pass_mean, pass_std, pass_corr]) else 1


if __name__ == "__main__":
    sys.exit(main())
