"""`wotl build` — one command rebuilds every output from raw data."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .clean import CleanStage
from .config import PipelineConfig
from .index import IndexStage
from .ingest import IngestStage, SampleIngestStage
from .join import JoinStage
from .map import MapStage
from .ownership import OwnershipStage
from .pipeline import Context, Pipeline
from .report import ReportStage


def build_pipeline(sample: bool) -> Pipeline:
    return Pipeline([
        SampleIngestStage() if sample else IngestStage(),
        CleanStage(),
        JoinStage(),
        IndexStage(),
        OwnershipStage(),
        ReportStage(),
        MapStage(),
    ])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wotl", description="Who Owns the Land? data pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="rebuild all outputs from data/raw")
    b.add_argument("--sample", action="store_true", help="use a synthetic city (no downloads, fake data)")
    b.add_argument("--config", type=Path, default=Path("config/pipeline.toml"))
    b.add_argument("-q", "--quiet", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO, format="%(message)s")
    cfg = PipelineConfig.load(args.config)
    ctx = build_pipeline(args.sample).run(Context(cfg, sample_mode=args.sample))
    logging.getLogger("wotl").info("outputs written to %s", ctx.outputs_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
