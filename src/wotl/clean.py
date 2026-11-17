"""Clean: standardise CRS, repair geometries, harmonise codes and names, resolve owner types.

Writes typed, privacy-safe GeoParquet into data/processed/ (fast to reload, tiny on disk).
"""

from __future__ import annotations

import logging
import re

import geopandas as gpd
import pandas as pd

from .config import OwnerRule, PipelineConfig
from .pipeline import Context, Stage
from .privacy import PrivacyGuard

log = logging.getLogger("wotl")

# Real-world layers use varied column names. First match wins; extend as sources are confirmed.
ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "sal_boundaries": {
        "sal_code": ("sal_code", "SAL_CODE", "SAL"),
        "place": ("place", "SP_NAME"),
        "main_place": ("main_place", "MP_NAME"),
    },
    "wards": {"ward_id": ("ward_id", "WARD_NAME", "WARD_ID", "WARD")},
    "suburbs": {"suburb": ("suburb", "OFC_SBRB_NAME", "SUBURB")},
    "informal_settlements": {"name": ("name", "INF_STLM_NAME", "NAME", "SETTLEMENT")},
    "parcels": {"sg26_code": ("sg26_code", "SG26_CODE"), "zoning": ("zoning", "ZONING")},
    "sg_public_places": {},
    "sg_streets": {},
    "sg_state_land": {},
}


def harmonise_code(s: pd.Series) -> pd.Series:
    """Codes as clean strings: no whitespace, no trailing '.0' from spreadsheets."""
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
        # classify unique values only — owner lists repeat owners a lot
        uniq = owners.drop_duplicates()
        lookup = dict(zip(uniq, map(self.classify_one, uniq), strict=False))
        return owners.map(lookup).astype(pd.CategoricalDtype(list(self.categories)))


class OwnerTypeResolver:
    """Assigns an owner TYPE to every parcel, most reliable evidence first:

    1. owner_types list (explicit type, or a raw owner name classified then discarded)
    2. Surveyor-General public layers (public places, streets, unalienated state land)
    3. `unknown` — never assumed to be private
    """

    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.classifier = OwnerTypeClassifier(cfg.owner_rules, cfg.owner_name_default, cfg.owner_categories)
        self._canon = {c.lower(): c for c in cfg.owner_categories}

    def _from_list(self, owner_types: pd.DataFrame | None) -> pd.DataFrame:
        if owner_types is None or owner_types.empty:
            return pd.DataFrame(columns=["sg26_code", "owner_type", "owner_source"])
        df = owner_types.rename(columns=str.lower).copy()
        if "sg26_code" not in df:
            raise ValueError("owner_types CSV needs an sg26_code column")
        typed = df.get("owner_type", pd.Series("", index=df.index)).fillna("").str.strip().str.lower()
        out = typed.map(self._canon)
        bad = typed[(typed != "") & out.isna()].unique()
        if len(bad):
            raise ValueError(f"owner_types: unknown owner_type values {list(bad)}; use {self.cfg.owner_categories}")
        if "owner_name" in df:  # classify names, then they go out of scope here and are never stored
            names = df["owner_name"].fillna("").str.strip()
            need = out.isna() & (names != "")
            out[need] = self.classifier.classify(names[need]).astype(str)
        source = df["source"].fillna("owner list") if "source" in df else "owner list"
        res = pd.DataFrame({"sg26_code": harmonise_code(df["sg26_code"]), "owner_type": out, "owner_source": source})
        return res.dropna(subset=["owner_type"]).drop_duplicates("sg26_code")

    def resolve(
        self,
        parcels: gpd.GeoDataFrame,
        owner_types: pd.DataFrame | None,
        public_layers: dict[str, gpd.GeoDataFrame],
    ) -> gpd.GeoDataFrame:
        parcels = parcels.copy()
        listed = self._from_list(owner_types).set_index("sg26_code")
        # object dtype: with no owner list yet these start all-NaN and must still accept text
        parcels["owner_type"] = parcels["sg26_code"].map(listed["owner_type"]).astype(object)
        parcels["owner_source"] = parcels["sg26_code"].map(listed["owner_source"]).astype(object)

        metric = self.cfg.metric_crs
        for sid, owner in self.cfg.owner_public_layers.items():
            layer = public_layers.get(sid)
            todo = parcels["owner_type"].isna()
            if layer is None or layer.empty or not todo.any():
                continue
            pts = gpd.GeoDataFrame(
                geometry=parcels.loc[todo].geometry.to_crs(metric).representative_point(), crs=metric
            )
            hit = gpd.sjoin(pts, layer[["geometry"]].to_crs(metric), predicate="within", how="inner")
            idx = hit.index.unique()
            parcels.loc[idx, "owner_type"] = owner
            parcels.loc[idx, "owner_source"] = sid
            log.info("  %s: %d parcels -> %s", sid, len(idx), owner)

        unknown = parcels["owner_type"].isna()
        parcels.loc[unknown, "owner_type"] = self.cfg.owner_unknown
        parcels.loc[unknown, "owner_source"] = "none"
        parcels["owner_type"] = parcels["owner_type"].astype(pd.CategoricalDtype(list(self.cfg.owner_categories)))
        log.info(
            "  owner types: %s",
            ", ".join(f"{k} {v:,}" for k, v in parcels["owner_type"].value_counts().items() if v),
        )
        return parcels


class CleanStage(Stage):
    name = "clean"

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        guard = PrivacyGuard(cfg.forbidden_columns, cfg.min_households)
        out = ctx.processed_dir
        out.mkdir(parents=True, exist_ok=True)

        # --- census (already canonical counts, built from the SuperWEB2 exports at ingest) ---
        census = ctx["census"].copy()
        census[cfg.census_key] = harmonise_code(census[cfg.census_key])
        census = census.groupby(cfg.census_key, as_index=False).sum(min_count=1)
        guard.assert_clean(census, "census")
        census.to_parquet(out / "census.parquet", index=False)
        ctx["census"] = census

        # --- vector layers ---
        for sid, keep in ALIASES.items():
            if f"{sid}_raw" not in ctx.tables:
                continue
            gdf = self._standardise(ctx[f"{sid}_raw"], keep, cfg.storage_crs)
            if sid == "sal_boundaries":
                gdf["sal_code"] = harmonise_code(gdf["sal_code"])
                gdf = gdf.dissolve("sal_code", as_index=False, aggfunc="first")  # multipart SALs -> one row
            if sid == "wards":
                gdf["ward_id"] = gdf["ward_id"].astype(str).str.strip()
                gdf["ward_id"] = gdf["ward_id"].where(~gdf["ward_id"].str.isdigit(), "Ward " + gdf["ward_id"])
            if sid == "suburbs":
                gdf["suburb"] = gdf["suburb"].astype(str).str.strip().str.title()
            if sid == "parcels":
                gdf["sg26_code"] = harmonise_code(gdf["sg26_code"])
            ctx[sid] = gdf

        public = {sid: ctx[sid] for sid in cfg.owner_public_layers if sid in ctx.tables}
        ctx["parcels"] = OwnerTypeResolver(cfg).resolve(ctx["parcels"], ctx.tables.get("owner_types_raw"), public)
        ctx.tables.pop("owner_types_raw", None)  # raw list (may hold names) is not kept beyond this point

        for sid in ALIASES:
            if sid in ctx.tables:
                gdf = guard.strip(ctx[sid])
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
