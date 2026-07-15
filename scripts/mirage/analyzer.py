"""
Schema analyzer: detects column types and collects statistics from real data.

Type taxonomy:
  - uuid         : UUIDv4 strings
  - numeric_int  : integer-valued numerics
  - numeric_float: float-valued numerics
  - timestamp    : ISO8601 / Unix timestamps
  - categorical  : low-cardinality strings (< MAX_CARDINALITY)
  - formatted    : matches known regex (email, phone, IBAN, URL)
  - free_text    : high-cardinality free text -> Markov model
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

MAX_CARDINALITY = 20  # below this, treat string column as categorical
# Above MAX_CARDINALITY but below MAX_EMPERICAL_TEXT_CARD, sample from observed
# values directly (fast + semantically faithful). Above that, fall back to Markov.
MAX_EMPIRICAL_TEXT_CARD = 2000

# --- Regex library for "formatted" string columns ------------------------------
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
EMAIL_RE = re.compile(r"^[\w\.\-]+@[\w\.\-]+\.\w{2,}$")
IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
URL_RE = re.compile(r"^https?://[\w\.\-/]+$")
PHONE_RE = re.compile(r"^\+?\d[\d\s\-\(\)]{7,}$")

REGEX_LIBRARY = [
    ("uuid", UUID_RE),
    ("email", EMAIL_RE),
    ("iban", IBAN_RE),
    ("url", URL_RE),
    ("phone", PHONE_RE),
]


@dataclass
class ColumnProfile:
    name: str
    col_type: str  # one of the types in the module docstring
    # Numeric / temporal
    sorted_values: Optional[np.ndarray] = None  # empirical quantile function
    # Correlation block membership (assigned by Synthesizer)
    corr_block: Optional[int] = None
    # Categorical
    categories: Optional[np.ndarray] = None
    probs: Optional[np.ndarray] = None
    # Formatted
    format_kind: Optional[str] = None
    # Free text (Markov)
    markov_table: Optional[dict] = None
    text_length_dist: Optional[np.ndarray] = None  # observed lengths
    # Timestamp
    ts_sorted_ms: Optional[np.ndarray] = None  # sorted epoch ms
    # Null handling
    null_prob: float = 0.0


def _detect_string_subtype(series: pd.Series) -> str:
    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return "free_text"

    # Try regex match on a sample
    sample = non_null.sample(min(200, len(non_null)), random_state=0)
    for kind, pattern in REGEX_LIBRARY:
        if sample.str.match(pattern).mean() > 0.95:
            return "formatted:" + kind

    # Cardinality check
    card = non_null.nunique()
    if card <= MAX_CARDINALITY:
        return "categorical"
    return "free_text"


def _is_timestamp_series(series: pd.Series) -> bool:
    """Try pandas to_datetime; if it parses most values, treat as timestamp."""
    if series.dtype.kind in ("M",):
        return True
    non_null = series.dropna()
    if len(non_null) == 0:
        return False
    sample = non_null.sample(min(200, len(non_null)), random_state=0)
    # Try common ISO formats first (fast path, no warning)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = pd.to_datetime(sample, format=fmt, errors="coerce")
            if parsed.notna().mean() > 0.95:
                return True
        except Exception:
            continue
    # Last-resort fallback (may emit warning, but we did our best above)
    try:
        with __import__("warnings").catch_warnings():
            __import__("warnings").simplefilter("ignore")
            parsed = pd.to_datetime(sample, errors="coerce", utc=False)
        return parsed.notna().mean() > 0.95
    except Exception:
        return False


def profile_column(name: str, series: pd.Series) -> ColumnProfile:
    null_prob = float(series.isna().mean())
    non_null = series.dropna()

    # Numeric?
    if pd.api.types.is_numeric_dtype(series):
        if pd.api.types.is_integer_dtype(series):
            col_type = "numeric_int"
        else:
            col_type = "numeric_float"
        sorted_vals = np.sort(non_null.to_numpy(dtype=float))
        return ColumnProfile(
            name=name,
            col_type=col_type,
            sorted_values=sorted_vals,
            null_prob=null_prob,
        )

    # Timestamp?
    if _is_timestamp_series(series):
        parsed = pd.to_datetime(non_null, errors="coerce", utc=False).dropna()
        # Convert to int64 nanoseconds, then to ms
        ts_ms = (parsed.astype("int64").to_numpy() // 10**6)
        return ColumnProfile(
            name=name,
            col_type="timestamp",
            ts_sorted_ms=np.sort(ts_ms),
            null_prob=null_prob,
        )

    # String subtypes
    subtype = _detect_string_subtype(series)
    if subtype.startswith("formatted:"):
        return ColumnProfile(
            name=name,
            col_type="formatted",
            format_kind=subtype.split(":", 1)[1],
            null_prob=null_prob,
        )
    if subtype == "categorical":
        cats = non_null.astype(str).value_counts().to_dict()
        categories = np.array(list(cats.keys()))
        probs = np.array(list(cats.values()), dtype=float)
        probs = probs / probs.sum()
        return ColumnProfile(
            name=name,
            col_type="categorical",
            categories=categories,
            probs=probs,
            null_prob=null_prob,
        )

    # Free text: if cardinality is moderate, fall back to empirical PMF
    # (much faster than Markov and statistically more faithful).
    strings = non_null.astype(str).to_numpy()
    n_unique = len(np.unique(strings))
    if n_unique <= MAX_EMPIRICAL_TEXT_CARD:
        # Empirical PMF over observed values
        uniq, counts = np.unique(strings, return_counts=True)
        probs = counts.astype(float) / counts.sum()
        return ColumnProfile(
            name=name,
            col_type="empirical_text",
            categories=uniq,
            probs=probs,
            null_prob=null_prob,
        )

    # Genuinely high-cardinality free text -> order-2 Markov
    return ColumnProfile(
        name=name,
        col_type="free_text",
        markov_table=_build_markov_table(strings),
        text_length_dist=np.array([len(s) for s in strings]),
        null_prob=null_prob,
    )


# --- Markov chain (order-2 character model) -----------------------------------
def _build_markov_table(strings: np.ndarray) -> dict:
    """
    Build an order-2 character Markov model.
    Returns:
        {
          'start': Counter of first 2 chars,
          'trans': dict[(c1,c2)] -> Counter(next char)
        }
    """
    from collections import defaultdict, Counter

    start_counter = Counter()
    trans = defaultdict(Counter)
    for s in strings:
        if len(s) == 0:
            continue
        if len(s) >= 2:
            start_counter[s[:2]] += 1
        else:
            start_counter[s] += 1
        # Walk the string
        for i in range(len(s) - 2):
            ctx = (s[i], s[i + 1])
            trans[ctx][s[i + 2]] += 1
        # Add terminal transition marker
        if len(s) >= 2:
            ctx = (s[-2], s[-1])
            trans[ctx]["<END>"] += 1

    # Convert Counters to (chars, probs) arrays for vectorized sampling
    start_chars = np.array(list(start_counter.keys()))
    start_probs = np.array(list(start_counter.values()), dtype=float)
    start_probs = start_probs / start_probs.sum()

    trans_arrays = {}
    for ctx, ctr in trans.items():
        chars = np.array(list(ctr.keys()))
        probs = np.array(list(ctr.values()), dtype=float)
        probs = probs / probs.sum()
        trans_arrays[ctx] = (chars, probs)

    return {
        "start_chars": start_chars,
        "start_probs": start_probs,
        "trans": trans_arrays,
    }
