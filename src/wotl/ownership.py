"""Land ownership overlay: share of each area's land by owner type."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .pipeline import Context, Stage

UNMAPPED = "Unmapped"  # roads, unregistered land, or gaps in the cadastre


class OwnershipOverlay:
    def __init__(self, parcels: gpd.GeoDataFrame, categories: tuple[str, ...], metric_crs: str) -> None:
        self.parcels = parcels.to_crs(metric_crs)[["owner_type", "geometry"]]
        self.categories = categories
        self.metric_crs = metric_crs

    @staticmethod
    def column(category: str) -> str:
        return f"own_{category.lower()}_pct"

    def shares(self, zones: gpd.GeoDataFrame, key: str) -> pd.DataFrame:
        """% of each zone's area by owner type, plus an Unmapped remainder and the dominant type."""
        z = zones.to_crs(self.metric_crs)[[key, "geometry"]]
        total = z.set_index(key).area
        ov = gpd.overlay(z, self.parcels, how="intersection", keep_geom_type=True)
        ov["a"] = ov.area
        piv = (
            ov.pivot_table(index=key, columns="owner_type", values="a", aggfunc="sum", observed=False)
            .reindex(index=total.index, columns=list(self.categories))
            .fillna(0.0)
        )
        pct = piv.div(total, axis=0).clip(upper=1) * 100
        pct[UNMAPPED] = (100 - pct.sum(axis=1)).clip(lower=0)
        dominant = pct[list(self.categories)].idxmax(axis=1).where(pct[list(self.categories)].max(axis=1) > 0)
        pct.columns = [self.column(c) for c in pct.columns]
        pct = pct.round(1).astype("float32")
        pct["dominant_owner"] = dominant
        return pct


class OwnershipStage(Stage):
    name = "ownership overlay"

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        overlay = OwnershipOverlay(ctx["parcels"], cfg.owner_categories, cfg.metric_crs)
        areas = ctx["areas"]
        ctx["areas"] = areas.join(overlay.shares(areas, "sal_code"), on="sal_code")
        stl = ctx["informal_settlements"]
        ctx["settlement_ownership"] = overlay.shares(stl, "name")
        ctx["ownership_columns"] = [overlay.column(c) for c in (*cfg.owner_categories, UNMAPPED)]
