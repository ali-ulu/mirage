"""
Synthesizer orchestrator.

Pipeline:
  1. Profile every column in the input DataFrame.
  2. Numeric columns -> Gaussian Copula (correlation block).
  3. Non-numeric columns -> independent samplers (categorical / formatted /
     free_text / timestamp).
  4. Reassemble into output DataFrame preserving original column order.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from .analyzer import profile_column, ColumnProfile
from .numeric import fit_copula, sample_copula
from .text import synthesize_column


@dataclass
class SynthesisResult:
    df: pd.DataFrame
    elapsed_ms: float
    rows_per_ms: float
    ms_per_row: float


class MirageSynthesizer:
    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        self.profiles: list[ColumnProfile] = []
        self.copula_model: Optional[object] = None
        self.numeric_indices: list[int] = []
        self.column_order: list[str] = []
        self._fitted = False

    def fit(self, df: pd.DataFrame) -> "MirageSynthesizer":
        """Profile columns and fit the copula on numeric columns."""
        self.column_order = list(df.columns)
        self.profiles = [profile_column(name, df[name]) for name in df.columns]

        # Collect numeric column indices
        self.numeric_indices = [
            i for i, p in enumerate(self.profiles)
            if p.col_type in ("numeric_int", "numeric_float")
        ]

        # Build numeric matrix and fit copula
        if self.numeric_indices:
            numeric_cols = [self.column_order[i] for i in self.numeric_indices]
            matrix = df[numeric_cols].to_numpy(dtype=float)
            self.copula_model = fit_copula(matrix)

        self._fitted = True
        return self

    def synthesize(self, n_rows: int) -> SynthesisResult:
        if not self._fitted:
            raise RuntimeError("Call .fit(df) first")
        rng = np.random.default_rng(self.seed)
        t0 = time.perf_counter()

        # Output container
        out = pd.DataFrame(index=range(n_rows))

        # 1. Numeric columns via copula
        if self.numeric_indices:
            numeric_samples = sample_copula(self.copula_model, n_rows, rng)
            for k, col_idx in enumerate(self.numeric_indices):
                profile = self.profiles[col_idx]
                col_name = self.column_order[col_idx]
                col_data = numeric_samples[:, k]
                if profile.col_type == "numeric_int":
                    col_data = np.round(col_data).astype(np.int64)
                out[col_name] = col_data
                # Apply nulls
                if profile.null_prob > 0:
                    null_mask = rng.random(n_rows) < profile.null_prob
                    out.loc[null_mask, col_name] = np.nan

        # 2. Non-numeric columns
        for i, profile in enumerate(self.profiles):
            if i in self.numeric_indices:
                continue
            col_name = self.column_order[i]
            out[col_name] = synthesize_column(profile, n_rows, rng)

        # Restore original column order
        out = out[self.column_order]

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        ms_per_row = elapsed_ms / n_rows if n_rows > 0 else 0.0
        return SynthesisResult(
            df=out,
            elapsed_ms=elapsed_ms,
            rows_per_ms=n_rows / elapsed_ms if elapsed_ms > 0 else float("inf"),
            ms_per_row=ms_per_row,
        )
