"""Clean: standardise CRS, repair geometries, harmonise codes and column names, classify owners.

Writes typed, privacy-safe GeoParquet into data/processed/ (fast to reload, tiny on disk).
"""

from __future__ import annotations

import re

import geopandas as gpd
import pandas as pd

from .config import OwnerRule
from .pipeline import Context, Stage
from .privacy import PrivacyGuard

# Real-world layers use varied column names. First match wins; extend as sources are confirmed.
ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "sal_boundaries": {"sal_code": ("sal_code", "SAL_CODE", "SAL", "sal")},
    "wards": {"ward_id": ("ward_id", "WARD_NAME", "WARD_ID", "WARD", "ward")},
    "informal_settlements": {"name": ("name", "INF_STLM_NAME", "NAME", "SETTLEMENT", "Name")},
    "parcels": {"owner_name": ("owner_name", "OWNER", "OWNER_NAME", "REGISTERED_OWNER"),
                "owner_type": ("owner_type", "OWNER_TYPE", "OWNERSHIP")},
}


def harmonise_code(s: pd.Series) -> pd.Series:
    """SAL codes as clean strings: no whitespace, no trailing '.0' from spreadsheets."""
    return s.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


class OwnerTypeClassifier:
    """Maps a raw registered-owner string to a coarse owner TYPE (never keeps the name)."""

    def __init__(self, rules: tuple[OwnerRule, ...], default: str, categories: tuple[str, ...]) -> None:
        self._rules = [(re.compile(r.pattern, re.IGNORECASE), r.type) for r in rules]
        self.default = default
        self.categories = categories

    def classify_one(self, owner: object) -> str:
        if not isinstance(owner, str) or not owner.strip():
            return "Other"
        for rx, t in self._rules:
            if rx.search(owner):
                return t
        return self.default

    def classify(self, owners: pd.Series) -> pd.Series:
        # classify unique values only — valuation rolls repeat owners a lot
        uniq = owners.drop_duplicates()
        lookup = dict(zip(uniq, map(self.classify_one, uniq), strict=False))
        return owners.map(lookup).astype(pd.CategoricalDtype(list(self.categories)))


class CleanStage(Stage):
    name = "clean"

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        guard = PrivacyGuard(cfg.forbidden_columns, cfg.min_households)
        out = ctx.processed_dir
        out.mkdir(parents=True, exist_ok=True)

        # --- census table ---
        census = ctx["census_raw"].rename(columns={v: k for k, v in cfg.census_column_map.items()})
        missing = set(cfg.census_column_map) - set(census.columns)
        if missing:
            raise ValueError(f"census table missing columns {sorted(missing)} — update [census.column_map]")
        census = census[list(cfg.census_column_map)].copy()
        census[cfg.census_key] = harmonise_code(census[cfg.census_key])
        num = [c for c in census.columns if c != cfg.census_key]
        census[num] = census[num].apply(pd.to_numeric, errors="coerce").astype("float32")
        census = census.groupby(cfg.census_key, as_index=False).sum(min_count=1)
        guard.assert_clean(census, "census")
        census.to_parquet(out / "census.parquet", index=False)
        ctx["census"] = census

        # --- vector layers ---
        classifier = OwnerTypeClassifier(cfg.owner_rules, cfg.owner_default, cfg.owner_categories)
        for sid, keep in ALIASES.items():
            gdf = self._standardise(ctx[f"{sid}_raw"], keep, cfg.storage_crs)
            if sid == "sal_boundaries":
                gdf["sal_code"] = harmonise_code(gdf["sal_code"])
                gdf = gdf.dissolve("sal_code", as_index=False)  # multipart SALs -> one row
            if sid == "parcels":
                if "owner_type" not in gdf or gdf["owner_type"].isna().all():
                    if "owner_name" not in gdf:
                        raise ValueError("parcels need an owner name or owner type column")
                    gdf["owner_type"] = classifier.classify(gdf["owner_name"])
                gdf = guard.strip(gdf)[["owner_type", "geometry"]]
            guard.assert_clean(gdf, sid)
            gdf.to_parquet(out / f"{sid}.parquet", index=False)
            ctx[sid] = gdf

    @staticmethod
    def _standardise(gdf: gpd.GeoDataFrame, aliases: dict[str, tuple[str, ...]], crs: str) -> gpd.GeoDataFrame:
        rename = {}
        for canon, options in aliases.items():
            hit = next((c for c in options if c in gdf.columns), None)
            if hit:
                rename[hit] = canon
        gdf = gdf.rename(columns=rename)
        cols = [c for c in aliases if c in gdf.columns] + ["geometry"]
        gdf = gdf[cols]
        if gdf.crs is None:
            raise ValueError("layer has no CRS — refusing to guess")
        gdf = gdf.to_crs(crs)
        gdf["geometry"] = gdf.geometry.make_valid()
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
        return gdf.reset_index(drop=True)
