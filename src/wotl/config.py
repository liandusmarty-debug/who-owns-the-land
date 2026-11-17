"""Typed, immutable view of config/pipeline.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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
    census_column_map: dict[str, str]
    owner_categories: tuple[str, ...]
    owner_default: str
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
        return cls(
            paths=Paths(root),
            storage_crs=raw["crs"]["storage"],
            metric_crs=raw["crs"]["metric"],
            min_households=int(raw["privacy"]["min_households"]),
            forbidden_columns=frozenset(c.lower() for c in raw["privacy"]["forbidden_columns"]),
            normaliser=idx["normaliser"],
            quintiles=int(idx["quintiles"]),
            indicators=tuple(
                IndicatorSpec(key=k, **v) for k, v in idx["indicators"].items()
            ),
            census_key=raw["census"]["key"],
            census_column_map=dict(raw["census"]["column_map"]),
            owner_categories=tuple(raw["ownership"]["categories"]),
            owner_default=raw["ownership"]["default"],
            owner_rules=tuple(OwnerRule(**r) for r in raw["ownership"]["rules"]),
            pilot_name=raw["pilot"]["name"],
            simplify_tolerance_m=float(raw["web"]["simplify_tolerance_m"]),
            coord_precision=int(raw["web"]["coord_precision"]),
            sources=tuple(SourceSpec(**s) for s in raw.get("sources", [])),
        )
