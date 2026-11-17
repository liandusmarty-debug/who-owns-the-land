"""Census 2011 small-area tables exported from Stats SA SuperWEB2.

SuperWEB2 exports one cross-tab CSV per table: a few title lines, a header row of answer
categories, then one row per small area (a 7-digit SAL code), and usually a footer. This module
turns a set of such files into one row per small area with the canonical counts used by the
deprivation index (see [census] in config/pipeline.toml).

Category labels are matched after normalising: lowercase and keep only a-z and 0-9, so
"Piped (tap) water inside yard" becomes "pipedtapwaterinsideyard". This makes the config
robust to punctuation and spacing differences between exports.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger("wotl")

SAL_CODE = re.compile(r"^\s*(?:SAL\s*)?(\d{7})\b")


def normalise(label: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(label).lower())


def _number(cell: str) -> float:
    cell = cell.strip().replace(" ", "").replace(",", "").replace(" ", "")
    if not cell or cell in {"-", "..", "x"}:
        return 0.0
    return float(cell)


def read_superweb_csv(path: Path) -> pd.DataFrame:
    """Parse a SuperWEB2 cross-tab export -> DataFrame indexed by sal_code, one column per category."""
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = [r for r in csv.reader(f)]

    code_col = first_data = None
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if SAL_CODE.match(cell) and any(c.strip() for c in row[j + 1 :]):
                code_col, first_data = j, i
                break
        if first_data is not None:
            break
    if first_data is None:
        raise ValueError(f"{path.name}: no rows with a 7-digit small-area code found")

    header = next(
        (r for r in reversed(rows[:first_data]) if sum(bool(c.strip()) for c in r[code_col + 1 :]) >= 2),
        None,
    )
    if header is None:
        raise ValueError(f"{path.name}: no header row of categories above the data")
    labels = [c.strip() for c in header[code_col + 1 :]]

    records: dict[str, list[float]] = {}
    for row in rows[first_data:]:
        if len(row) <= code_col or not (m := SAL_CODE.match(row[code_col])):
            continue
        values = row[code_col + 1 : code_col + 1 + len(labels)]
        records[m.group(1)] = [_number(v) for v in values] + [0.0] * (len(labels) - len(values))

    df = pd.DataFrame.from_dict(records, orient="index", columns=labels)
    df = df.loc[:, [bool(c) for c in df.columns]]  # drop the empty column a trailing comma creates
    df.index.name = "sal_code"
    return df


@dataclass(frozen=True)
class CountRule:
    """A canonical count: sum of categories matching `match`, or the valid total minus `not_match`."""

    name: str
    match: tuple[str, ...] = ()
    not_match: tuple[str, ...] = ()

    def apply(self, valid: pd.DataFrame, table: str) -> pd.Series:
        norm = {c: normalise(c) for c in valid.columns}
        patterns = self.match or self.not_match
        hits = [c for c, n in norm.items() if any(re.search(p, n) for p in patterns)]
        if not hits:
            raise ValueError(
                f"census table {table!r}: rule {self.name!r} matched no categories. "
                f"Available (normalised): {sorted(norm.values())}"
            )
        matched = valid[hits].sum(axis=1)
        return matched if self.match else valid.sum(axis=1) - matched


@dataclass(frozen=True)
class TableSpec:
    key: str
    file: str
    total: str | None = None  # name for the sum of valid categories
    total_all: str | None = None  # name for the sum of every category (e.g. population)
    counts: tuple[CountRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_config(cls, key: str, raw: dict) -> TableSpec:
        counts = []
        for name, rule in raw.get("counts", {}).items():
            counts.append(CountRule(name, tuple(rule.get("match", ())), tuple(rule.get("not", ()))))
        return cls(key, raw.get("file", key), raw.get("total"), raw.get("total_all"), tuple(counts))


class Census2011Builder:
    """Builds the canonical census table from a folder of SuperWEB2 exports."""

    def __init__(self, tables: tuple[TableSpec, ...], exclude: tuple[str, ...]) -> None:
        self.tables = tables
        self.exclude = [re.compile(p) for p in exclude]

    def _file(self, folder: Path, spec: TableSpec) -> Path:
        hits = [p for p in folder.glob("*.csv") if p.stem.lower() == spec.file.lower()]
        if not hits:
            raise FileNotFoundError(
                f"census table {spec.key!r}: expected {folder / (spec.file + '.csv')} "
                "(export it from SuperWEB2, see docs/DATA-SOURCES.md)"
            )
        return hits[0]

    def build(self, folder: Path) -> pd.DataFrame:
        parts = []
        for spec in self.tables:
            raw = read_superweb_csv(self._file(folder, spec))
            valid = raw[[c for c in raw.columns if not any(rx.search(normalise(c)) for rx in self.exclude)]]
            part = pd.DataFrame(index=raw.index)
            if spec.total:
                part[spec.total] = valid.sum(axis=1)
            if spec.total_all:
                totals = [c for c in raw.columns if normalise(c) != "total"]
                part[spec.total_all] = raw[totals].sum(axis=1)
            for rule in spec.counts:
                part[rule.name] = rule.apply(valid, spec.key)
            log.info("  census %s: %d small areas, %d categories", spec.key, len(raw), raw.shape[1])
            parts.append(part)
        out = pd.concat(parts, axis=1, join="outer").fillna(0).astype("float32")
        return out.reset_index()
