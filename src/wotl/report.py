"""Tabular and written outputs: neighbourhood_profiles.csv, summary.md, pilot profile."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .pipeline import Context, Stage
from .privacy import PrivacyGuard

STANDING_CAVEATS = [
    "Census 2022 had undercount issues, especially in informal settlements; rates there may be understated.",
    "Small areas have small populations; areas below the household threshold are suppressed and not ranked.",
    "Cadastral and valuation-roll ownership does not reflect informal occupation or customary rights.",
    "The deprivation index is relative: it ranks areas against each other within the city, "
    "not against a fixed standard.",
]


def area_label(df: pd.DataFrame) -> pd.Series:
    ward = df["ward_id"].fillna("Unknown ward")
    return df["settlement"].fillna(ward).astype(str) + " · SAL " + df["sal_code"].astype(str)


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    rows = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        rows.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |")
    return "\n".join(rows)


class ReportStage(Stage):
    name = "reports"

    def run(self, ctx: Context) -> None:
        cfg = ctx.config
        out = ctx.outputs_dir
        out.mkdir(parents=True, exist_ok=True)
        areas = ctx["areas"].copy()
        areas["area_name"] = area_label(areas)
        ctx["areas"] = areas
        own_cols = ctx["ownership_columns"]
        ind_cols = [f"pct_{s.key}" for s in cfg.indicators]

        cols = [
            "sal_code",
            "area_name",
            "ward_id",
            "settlement",
            "population",
            "households",
            "area_km2",
            "suppressed",
            *ind_cols,
            "deprivation_index",
            "deprivation_rank",
            "deprivation_quintile",
            *own_cols,
            "dominant_owner",
        ]
        table = pd.DataFrame(areas[cols]).sort_values("deprivation_rank", na_position="last")
        table.loc[table["suppressed"], ["population", "households"]] = np.nan
        table[["population", "households"]] = table[["population", "households"]].round().astype("Int64")
        PrivacyGuard(cfg.forbidden_columns, cfg.min_households).assert_clean(table, "profiles")
        table.round(3).to_csv(out / "neighbourhood_profiles.csv", index=False)

        caveats = STANDING_CAVEATS + ctx.tables.get("caveats", [])
        ctx["caveats_all"] = caveats
        (out / "summary.md").write_text(self._summary(ctx, table, own_cols, caveats), encoding="utf-8")
        (out / f"profile_{cfg.pilot_name.lower()}.md").write_text(self._pilot(ctx, own_cols), encoding="utf-8")

    # -- summary ------------------------------------------------------------
    def _summary(self, ctx: Context, table: pd.DataFrame, own_cols: list[str], caveats: list[str]) -> str:
        cfg = ctx.config
        top = table.dropna(subset=["deprivation_rank"]).head(20)
        top_view = top[
            ["deprivation_rank", "area_name", "ward_id", "households", "deprivation_index", "dominant_owner"]
        ].copy()
        top_view["deprivation_index"] = top_view["deprivation_index"].round(2)
        top_view["households"] = top_view["households"].astype("Int64")
        top_view.columns = ["Rank", "Area", "Ward", "Households", "Index", "Main owner type"]

        a = ctx["areas"]
        tot_area = a["area_km2"].sum()
        city_mix = pd.Series({c: float((a[c] * a["area_km2"]).sum() / tot_area) for c in own_cols}).round(1)
        q5 = a[a["deprivation_quintile"] == cfg.quintiles]
        q5_area = max(float(q5["area_km2"].sum()), 1e-9)
        q5_mix = pd.Series({c: float((q5[c] * q5["area_km2"]).sum()) / q5_area for c in own_cols}).round(1)
        mix = pd.DataFrame(
            {
                "Owner type": [c.removeprefix("own_").removesuffix("_pct").title() for c in own_cols],
                "All areas (% of land)": city_mix.values,
                "Most deprived quintile (% of land)": q5_mix.values,
            }
        )
        stl = ctx["settlement_ownership"].reset_index()
        stl[stl.select_dtypes("float").columns] = stl.select_dtypes("float").astype(float).round(1)
        stl.columns = ["Settlement"] + [
            c.removeprefix("own_").removesuffix("_pct").title() if c.startswith("own_") else c.replace("_", " ").title()
            for c in stl.columns[1:]
        ]

        banner = "> **SYNTHETIC SAMPLE DATA — for development only. Not real findings.**\n\n" if ctx.sample_mode else ""
        return (
            f"# Who Owns the Land? — City of Cape Town neighbourhood summary\n\n{banner}"
            f"_Generated {date.today().isoformat()} · {len(a)} small areas · "
            f"{int(a['suppressed'].sum())} suppressed · index: {cfg.normaliser}, "
            f"{len(cfg.indicators)} indicators_\n\n"
            "## 20 most deprived small areas\n\n"
            f"{_md_table(top_view)}\n\n"
            "## Land ownership by owner type\n\n"
            f"{_md_table(mix)}\n\n"
            "## Ownership within informal settlements (% of settlement area)\n\n"
            f"{_md_table(stl)}\n\n"
            "## Method\n\n"
            "Each indicator is a percentage of households (or adults / labour force). Indicators are "
            f"normalised ({cfg.normaliser}), averaged with configurable weights, ranked (1 = most deprived) "
            f"and split into {cfg.quintiles} groups ({cfg.quintiles} = most deprived).\n\n"
            "## Caveats\n\n" + "\n".join(f"- {c}" for c in caveats) + "\n"
        )

    # -- pilot profile ----------------------------------------------------------
    def _pilot(self, ctx: Context, own_cols: list[str]) -> str:
        cfg = ctx.config
        a = ctx["areas"]
        sub = a[a["settlement"] == cfg.pilot_name]
        banner = "> **SYNTHETIC SAMPLE DATA — for development only.**\n\n" if ctx.sample_mode else ""
        if sub.empty:
            return f"# {cfg.pilot_name} profile\n\n{banner}No small areas matched this settlement name.\n"

        lines = [
            f"# {cfg.pilot_name} — area profile\n",
            banner.rstrip("\n"),
            f"**Small areas:** {len(sub)} · **Households:** {int(sub['households'].sum()):,} · "
            f"**People:** {int(sub['population'].sum()):,} · **Area:** {sub['area_km2'].sum():.2f} km²\n",
            f"**City rank of its most deprived small area:** "
            f"{int(sub['deprivation_rank'].min()) if sub['deprivation_rank'].notna().any() else 'n/a'} "
            f"of {int(a['deprivation_rank'].max())}\n",
            "## Living conditions (pooled across the area vs. city)\n",
            "| Indicator | " + cfg.pilot_name + " | City |",
            "|---|---|---|",
        ]
        for s in cfg.indicators:
            local = sub[s.numerator].sum() / max(sub[s.denominator].sum(), 1) * 100
            city = a[s.numerator].sum() / max(a[s.denominator].sum(), 1) * 100
            lines.append(f"| {s.label} | {local:.1f}% | {city:.1f}% |")

        lines += ["", "## Who owns the land under it\n", "| Owner type | % of settlement area |", "|---|---|"]
        so = ctx["settlement_ownership"]
        if cfg.pilot_name in so.index:
            row = so.loc[cfg.pilot_name]
            for c in own_cols:
                lines.append(f"| {c.removeprefix('own_').removesuffix('_pct').title()} | {row[c]:.1f}% |")
        lines += ["", "## Caveats\n", *[f"- {c}" for c in ctx["caveats_all"]], ""]
        return "\n".join(lines)
