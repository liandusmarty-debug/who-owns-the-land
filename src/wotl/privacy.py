"""POPIA guard-rails. Area-level only: nothing that identifies a person leaves the clean stage."""

from __future__ import annotations

import pandas as pd


class PrivacyError(RuntimeError):
    pass


class PrivacyGuard:
    def __init__(self, forbidden_columns: frozenset[str], min_households: int) -> None:
        self.forbidden = forbidden_columns
        self.min_households = min_households

    def strip(self, df: pd.DataFrame) -> pd.DataFrame:
        """Drop any forbidden (personal) columns."""
        drop = [c for c in df.columns if c.lower() in self.forbidden]
        return df.drop(columns=drop) if drop else df

    def assert_clean(self, df: pd.DataFrame, where: str) -> None:
        bad = [c for c in df.columns if c.lower() in self.forbidden]
        if bad:
            raise PrivacyError(f"{where}: personal columns present {bad} — refusing to write")

    def flag_small_areas(self, df: pd.DataFrame, households_col: str = "households") -> pd.Series:
        """True where an area is too small to publish rates for."""
        return df[households_col].fillna(0) < self.min_households
