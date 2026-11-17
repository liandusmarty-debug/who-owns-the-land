"""Typed, immutable view of config/pipeline.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .census import TableSpec


@dataclass(frozen=True, slots=True)
class IndicatorSpec:
    key: str
    label: str
    numerator: str
    denominator: str
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class OwnerRule:
    pattern: str
    type: str


@dataclass(frozen=True, slots=True)
class SourceSpec:
    id: str
    title: str
    publisher: str
    licence: str
    url: str = ""
    notes: str = ""
    kind: str = "file"  # "file" (plain download) or "arcgis" (paged ArcGIS REST layer query)
    where: str = "1=1"  # arcgis: attribute filter
    out_fields: str = "*"  # arcgis: comma-separated fields to keep (drop anything personal here)
    bbox: tuple[float, float, float, float] | None = None  # arcgis: lon/lat envelope filter


@dataclass(frozen=True, slots=True)
class Paths:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def outputs(self) -> Path:
        return self.root / "outputs"

    @property
    def web_src(self) -> Path:
        return self.root / "web"


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    paths: Paths
    storage_crs: str
    metric_crs: str
    min_households: int
    forbidden_columns: frozenset[str]
    normaliser: str
    quintiles: int
    indicators: tuple[IndicatorSpec, ...]
    census_key: str
    census_tables: tuple[TableSpec, ...]
    census_exclude: tuple[str, ...]
    owner_categories: tuple[str, ...]
    owner_unknown: str
    owner_name_default: str
    owner_public_layers: dict[str, str]
    owner_rules: tuple[OwnerRule, ...]
    pilot_name: str
    simplify_tolerance_m: float
    coord_precision: int
    sources: tuple[SourceSpec, ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, path: Path, root: Path | None = None) -> PipelineConfig:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        root = root or path.resolve().parent.parent
        idx = raw["index"]
        own = raw["ownership"]
        if own["unknown"] not in own["categories"]:
            raise ValueError("[ownership] unknown must be one of the categories")
        return cls(
            paths=Paths(root),
            storage_crs=raw["crs"]["storage"],
            metric_crs=raw["crs"]["metric"],
            min_households=int(raw["privacy"]["min_households"]),
            forbidden_columns=frozenset(c.lower() for c in raw["privacy"]["forbidden_columns"]),
            normaliser=idx["normaliser"],
            quintiles=int(idx["quintiles"]),
            indicators=tuple(IndicatorSpec(key=k, **v) for k, v in idx["indicators"].items()),
            census_key=raw["census"]["key"],
            census_tables=tuple(TableSpec.from_config(k, v) for k, v in raw["census"]["tables"].items()),
            census_exclude=tuple(raw["census"].get("exclude", ())),
            owner_categories=tuple(own["categories"]),
            owner_unknown=own["unknown"],
            owner_name_default=own["name_default"],
            owner_public_layers=dict(own.get("public_layers", {})),
            owner_rules=tuple(OwnerRule(**r) for r in own["rules"]),
            pilot_name=raw["pilot"]["name"],
            simplify_tolerance_m=float(raw["web"]["simplify_tolerance_m"]),
            coord_precision=int(raw["web"]["coord_precision"]),
            sources=tuple(
                SourceSpec(**{**s, "bbox": tuple(s["bbox"]) if "bbox" in s else None}) for s in raw.get("sources", [])
            ),
        )
