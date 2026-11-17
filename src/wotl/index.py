"""Composite deprivation index per SAL.

Indicator  -> a rate (numerator / denominator)
Normaliser -> puts rates on a common scale (strategy pattern: z-score or min-max)
DeprivationIndex -> weighted mean of normalised indicators, rank and quintile
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from .config import IndicatorSpec
from .pipeline import Context, Stage
from .privacy import PrivacyGuard


class Normaliser(ABC):
    @abstractmethod
    def __call__(self, s: pd.Series) -> pd.Series: ...

    @staticmethod
    def create(kind: str) -> Normaliser:
        try:
            return {"zscore": ZScore, "minmax": MinMax}[kind]()
        except KeyError:
            raise ValueError(f"unknown normaliser {kind!r} (use 'zscore' or 'minmax')") from None


class ZScore(Normaliser):
    def __call__(self, s: pd.Series) -> pd.Series:
        sd = s.std(ddof=0)
        return (s - s.mean()) / sd if sd else s * 0.0


class MinMax(Normaliser):
    def __call__(self, s: pd.Series) -> pd.Series:
        lo, hi = s.min(), s.max()
        return (s - lo) / (hi - lo) if hi > lo else s * 0.0


class Indicator:
    def __init__(self, spec: IndicatorSpec) -> None:
        self.spec = spec

    @property
    def column(self) -> str:
        return f"pct_{self.spec.key}"

    def rate(self, df: pd.DataFrame) -> pd.Series:
        num = df[self.spec.numerator].astype("float64")
        den = df[self.spec.denominator].astype("float64").replace(0, np.nan)
        return (num / den).clip(0, 1) * 100.0


class DeprivationIndex:
    def __init__(self, indicators: list[Indicator], normaliser: Normaliser, quintiles: int = 5) -> None:
        if not indicators:
            raise ValueError("at least one indicator is required")
        self.indicators = indicators
        self.normaliser = normaliser
        self.quintiles = quintiles

    def compute(self, df: pd.DataFrame, eligible: pd.Series) -> pd.DataFrame:
        """Return indicator rates plus index/rank/quintile; ineligible rows get NaN index."""
        out = pd.DataFrame(index=df.index)
        for ind in self.indicators:
            out[ind.column] = ind.rate(df).astype("float32")

        weights = np.array([i.spec.weight for i in self.indicators], dtype="float64")
        pool = out.loc[eligible, [i.column for i in self.indicators]]
        norm = pool.apply(self.normaliser)
        # weighted mean over available indicators (a missing indicator doesn't zero the score)
        mask = norm.notna().to_numpy()
        vals = np.nan_to_num(norm.to_numpy()) * weights
        wsum = (mask * weights).sum(axis=1)
        score = np.where(wsum > 0, vals.sum(axis=1) / np.where(wsum > 0, wsum, 1), np.nan)

        out["deprivation_index"] = np.nan
        out.loc[pool.index, "deprivation_index"] = score
        out["deprivation_rank"] = out["deprivation_index"].rank(ascending=False, method="min").astype("Int32")
        valid = out["deprivation_index"].notna()
        out["deprivation_quintile"] = pd.Series(pd.NA, index=out.index, dtype="Int8")
        if valid.sum() >= self.quintiles:
            out.loc[valid, "deprivation_quintile"] = (
                pd.qcut(out.loc[valid, "deprivation_index"].rank(method="first"), self.quintiles, labels=False) + 1
            ).astype("Int8")
        return out


class IndexStage(Stage):
    name = "deprivation index"

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        areas = ctx["areas"]
        guard = PrivacyGuard(cfg.forbidden_columns, cfg.min_households)
        areas["suppressed"] = guard.flag_small_areas(areas)
        index = DeprivationIndex(
            [Indicator(s) for s in cfg.indicators], Normaliser.create(cfg.normaliser), cfg.quintiles
        )
        result = index.compute(areas, eligible=~areas["suppressed"])
        # don't publish rates for suppressed areas
        rate_cols = [c for c in result.columns if c.startswith("pct_")]
        result.loc[areas["suppressed"], rate_cols] = np.nan
        ctx["areas"] = areas.join(result)
        n = int(areas["suppressed"].sum())
        if n:
            ctx.tables.setdefault("caveats", []).append(
                f"{n} small areas with fewer than {cfg.min_households} households were suppressed and not ranked."
            )
