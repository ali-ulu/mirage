"""
Numeric synthesizer using Gaussian Copula + Empirical CDF.

Algorithm:
  Fit:
    1. Rank-based empirical CDF:   u_ij = rank(x_ij) / (n+1)
    2. Inverse normal transform:   z_ij = Phi^-1(u_ij)
    3. Pearson correlation of z:   Sigma_z  (close to Spearman of original)
    4. Store sorted original values per column.

  Sample:
    1. z ~ N(0, Sigma_z), shape (m, d)
    2. u = Phi(z)
    3. x = sorted_j[ floor(u * n) ]   (empirical inverse CDF lookup)

This preserves:
  - marginal distributions exactly (because of empirical inverse CDF)
  - correlation structure (because of copula correlation)
  - mean and std-dev approximately (as a consequence of the above)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm


@dataclass
class CopulaModel:
    sorted_cols: np.ndarray  # shape (n, d)
    corr: np.ndarray         # shape (d, d)
    n: int
    d: int


def fit_copula(numeric_matrix: np.ndarray) -> CopulaModel:
    """
    Fit Gaussian Copula on a numeric matrix (n_samples, n_features).
    NaN values are imputed with column mean before fitting.
    """
    n, d = numeric_matrix.shape
    # Impute NaNs with column means
    matrix = numeric_matrix.copy()
    col_means = np.nanmean(matrix, axis=0)
    nan_mask = np.isnan(matrix)
    for j in range(d):
        matrix[nan_mask[:, j], j] = col_means[j]

    # Rank-based empirical CDF: u_ij = rank(x_ij) / (n+1)
    # Using scipy.stats.rankdata would be slow; use argsort-based rank.
    ranks = np.zeros_like(matrix)
    for j in range(d):
        order = np.argsort(matrix[:, j], kind="stable")
        # ranks[order[k]] = k+1
        ranks[order, j] = np.arange(1, n + 1)
    u = ranks / (n + 1.0)
    # Clip to avoid +/-inf at 0 and 1
    u = np.clip(u, 1e-6, 1.0 - 1e-6)

    # Inverse normal transform
    z = norm.ppf(u)

    # Correlation of z (Pearson on z == approx Spearman on original)
    # Edge case: tek kolon varsa corrcoef skaler döner, 1x1 matris olmalı
    if d == 1:
        corr = np.array([[1.0]])
    else:
        corr = np.corrcoef(z.T)
    # Ensure PD (positive definite) — add tiny ridge if needed
    if not np.all(np.linalg.eigvalsh(corr) > 0):
        corr = corr + 1e-6 * np.eye(d)

    sorted_cols = np.sort(matrix, axis=0)
    return CopulaModel(sorted_cols=sorted_cols, corr=corr, n=n, d=d)


def sample_copula(model: CopulaModel, m: int, rng: np.random.Generator) -> np.ndarray:
    """
    Sample m rows from the fitted copula.
    Returns matrix of shape (m, d).
    """
    # Sample from MVN(0, Sigma_z)
    z_samples = rng.multivariate_normal(
        mean=np.zeros(model.d), cov=model.corr, size=m, method="cholesky"
    )
    # To uniform
    u_samples = norm.cdf(z_samples)
    # Empirical inverse CDF lookup
    indices = (u_samples * model.n).astype(np.int64).clip(0, model.n - 1)
    # For each column j: out[:,j] = sorted[:,j][indices[:,j]]
    # np.take_along_axis works because sorted_cols and indices share dim 1
    out = np.take_along_axis(model.sorted_cols, indices, axis=0)
    return out
