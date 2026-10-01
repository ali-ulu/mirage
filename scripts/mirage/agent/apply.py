"""
MIRAGE — Decoy planı uygulama (anonymization / decoy üretimi).

Planner Agent'ın ürettiği `DecoyPlan`'ı alır ve tabloyu gerçekten dönüştürür:
`decoy` kolonları sentetik veriyle değiştirilir, `keep` kolonları **aynen**
korunur. Satır sayısı ve kolon sırası değişmez; bu, ilişkisel bütünlüğü ve
raporlama şemalarını bozmadan hassas alanları maskelemeyi sağlar.

Deterministik: aynı `seed` + aynı girdi → aynı çıktı.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from ..synthesizer import MirageSynthesizer
from .planner import DecoyPlan


def apply_decoy_plan(
    df: pd.DataFrame,
    plan: DecoyPlan,
    *,
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """
    `plan`'a göre tabloyu dönüştürür.

    Args:
        df: kaynak tablo (değiştirilmez).
        plan: hangi kolonların decoy olacağını belirten plan.
        seed: sentetik üretim için tohum (tekrarlanabilirlik).

    Returns:
        Yeni DataFrame — decoy kolonlar sentetik, keep kolonlar orijinal;
        satır sayısı ve kolon sırası korunur.
    """
    decoy_cols = [c for c in plan.decoy_columns if c in df.columns]
    if not decoy_cols:
        return df.copy()

    synth = MirageSynthesizer(seed=seed).fit(df)
    synthetic = synth.synthesize(len(df)).df.reset_index(drop=True)

    out = df.copy().reset_index(drop=True)
    for col in decoy_cols:
        out[col] = synthetic[col].to_numpy()
    return out[out.columns]
