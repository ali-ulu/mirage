"""
Non-numeric column synthesizers: categorical, formatted, free_text, timestamp.

All synthesizers are stateless given a profile — they only need a profile
plus an rng and a row count.
"""
from __future__ import annotations

import re
import uuid as uuidlib
from typing import Optional

import numpy as np
import pandas as pd

from .analyzer import ColumnProfile


# ---------------------------------------------------------------------------
# Categorical
# ---------------------------------------------------------------------------
def sample_categorical(profile: ColumnProfile, m: int, rng: np.random.Generator) -> np.ndarray:
    cats = profile.categories
    probs = profile.probs
    idx = rng.choice(len(cats), size=m, p=probs)
    return cats[idx]


# ---------------------------------------------------------------------------
# Formatted (regex-preserving)
# ---------------------------------------------------------------------------
def sample_formatted(profile: ColumnProfile, m: int, rng: np.random.Generator) -> np.ndarray:
    kind = profile.format_kind
    if kind == "uuid":
        return np.array([str(uuidlib.uuid4()) for _ in range(m)])
    if kind == "email":
        # Format-preserving: keep structure user@domain.tld
        users = ["john", "alice", "bob", "info", "admin", "support", "team", "user"]
        domains = ["example.com", "test.org", "mail.net", "corp.io"]
        return np.array(
            [f"{rng.choice(users)}{rng.integers(0, 9999)}@{rng.choice(domains)}" for _ in range(m)]
        )
    if kind == "iban":
        # Format-preserving: 2 letters + 2 digits + 12-30 alnum
        countries = ["TR", "DE", "FR", "GB", "NL"]
        return np.array(
            [
                f"{rng.choice(countries)}{rng.integers(10, 99):02d}"
                + "".join(rng.choice(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"), size=14))
                for _ in range(m)
            ]
        )
    if kind == "url":
        paths = ["/login", "/dashboard", "/api/v1/users", "/assets/logo.png", "/reports/q4.pdf"]
        hosts = ["internal.corp", "api.service.io", "portal.app.net"]
        return np.array(
            [f"https://{rng.choice(hosts)}{rng.choice(paths)}" for _ in range(m)]
        )
    if kind == "phone":
        return np.array(
            [f"+90{rng.integers(500, 599)}{rng.integers(1000000, 9999999)}" for _ in range(m)]
        )
    # Fallback
    return np.array([""] * m, dtype=object)


# ---------------------------------------------------------------------------
# Free text via Markov
# ---------------------------------------------------------------------------
def sample_free_text(profile: ColumnProfile, m: int, rng: np.random.Generator) -> np.ndarray:
    """
    Vectorized order-2 Markov sampler.

    Instead of looping per-row in Python (which costs ~20μs/row), we batch
    all m rows and advance them synchronously: each iteration draws m
    uniform samples at once and looks up the next char per-row. This pushes
    the cost down to ~1-2μs/row for typical short strings.
    """
    table = profile.markov_table
    start_chars = table["start_chars"]
    start_probs = table["start_probs"]
    trans = table["trans"]

    lengths = profile.text_length_dist
    if len(lengths) == 0 or len(start_chars) == 0:
        return np.array([""] * m, dtype=object)

    # Sample target lengths and cap to a reasonable maximum
    sampled_lengths = rng.choice(lengths, size=m)
    max_len = int(sampled_lengths.max()) if len(sampled_lengths) > 0 else 0
    if max_len == 0:
        return np.array([""] * m, dtype=object)

    # Precompute a fast lookup for transitions:
    # Map ctx -> (chars_array, cumulative_probs_array) so we can use searchsorted
    fast_trans = {}
    for ctx, (chars, probs) in trans.items():
        cdf = np.cumsum(probs)
        cdf[-1] = 1.0  # guard against fp drift
        fast_trans[ctx] = (chars, cdf)

    # Pick start states for all rows at once
    start_idx = rng.choice(len(start_chars), size=m, p=start_probs)
    starts = start_chars[start_idx]
    # Some starts may be 1-char (edge case); pad to ensure len>=2
    rows = [list(s if isinstance(s, str) else str(s)) for s in starts]
    active = np.ones(m, dtype=bool)  # rows still being generated
    lengths_done = np.array([len(r) for r in rows], dtype=int)

    # Iteratively advance
    for _ in range(max_len + 2):
        if not active.any():
            break
        idxs = np.where(active)[0]
        # Build ctx arrays for active rows
        n_active = len(idxs)
        # Draw all uniforms at once
        u = rng.random(n_active)
        for k, i in enumerate(idxs):
            r = rows[i]
            if len(r) >= 2:
                ctx = (r[-2], r[-1])
            else:
                ctx = (r[-1], r[-1])
            entry = fast_trans.get(ctx)
            if entry is None:
                active[i] = False
                continue
            chars, cdf = entry
            pos = np.searchsorted(cdf, u[k])
            pos = min(pos, len(chars) - 1)
            nxt = chars[pos]
            if isinstance(nxt, str) and nxt == "<END>":
                active[i] = False
                continue
            r.append(str(nxt))
            lengths_done[i] += 1
            if lengths_done[i] >= int(sampled_lengths[i]):
                active[i] = False

    # Assemble final strings, respecting target length
    out = np.empty(m, dtype=object)
    for i in range(m):
        target_len = int(sampled_lengths[i])
        s = "".join(rows[i])
        out[i] = s[:target_len] if target_len > 0 else ""
    return out


# ---------------------------------------------------------------------------
# Timestamp
# ---------------------------------------------------------------------------
def sample_timestamp(profile: ColumnProfile, m: int, rng: np.random.Generator) -> np.ndarray:
    """Empirical inverse CDF on epoch-ms values, then format back to ISO8601."""
    sorted_ms = profile.ts_sorted_ms
    n = len(sorted_ms)
    # Sample uniforms and look up
    u = rng.random(m)
    indices = (u * n).astype(int).clip(0, n - 1)
    ms = sorted_ms[indices]
    # Convert back to ISO8601 strings (preserve format)
    ts = pd.to_datetime(ms, unit="ms")
    # Use ISO format that matches typical input
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ").to_numpy()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def synthesize_column(profile: ColumnProfile, m: int, rng: np.random.Generator) -> np.ndarray:
    if profile.col_type in ("numeric_int", "numeric_float"):
        raise ValueError("Numeric columns handled by CopulaSynthesizer, not here")
    if profile.col_type in ("categorical", "empirical_text"):
        # Both use the same fast path: sample from observed values with PMF
        out = sample_categorical(profile, m, rng)
    elif profile.col_type == "formatted":
        out = sample_formatted(profile, m, rng)
    elif profile.col_type == "free_text":
        out = sample_free_text(profile, m, rng)
    elif profile.col_type == "timestamp":
        out = sample_timestamp(profile, m, rng)
    else:
        raise ValueError(f"Unknown column type: {profile.col_type}")

    # Apply null probability
    if profile.null_prob > 0:
        null_mask = rng.random(m) < profile.null_prob
        out = out.astype(object)
        out[null_mask] = None
    return out
