"""Core pipeline abstractions: a shared Context and an ordered list of Stages.

Each stage is a small class with one job. Stages read and write named tables on
the Context, so they can be tested in isolation and reordered or swapped
(e.g. a SampleIngest instead of a real download) without touching the others.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import PipelineConfig

log = logging.getLogger("wotl")


@dataclass
class Context:
    config: PipelineConfig
    tables: dict[str, Any] = field(default_factory=dict)
    sample_mode: bool = False

    @property
    def processed_dir(self) -> Path:
        p = self.config.paths.processed
        return p / "_sample" if self.sample_mode else p

    @property
    def outputs_dir(self) -> Path:
        p = self.config.paths.outputs
        return p / "_sample" if self.sample_mode else p

    def __getitem__(self, name: str) -> Any:
        try:
            return self.tables[name]
        except KeyError:
            raise KeyError(f"table {name!r} not produced yet — check stage order") from None

    def __setitem__(self, name: str, value: Any) -> None:
        self.tables[name] = value


class Stage(ABC):
    """One step of the pipeline."""

    name: str = "stage"

    @abstractmethod
    def run(self, ctx: Context) -> None: ...


class Pipeline:
    def __init__(self, stages: list[Stage]) -> None:
        self.stages = stages

    def run(self, ctx: Context) -> Context:
        for stage in self.stages:
            t0 = time.perf_counter()
            log.info("▶ %s", stage.name)
            stage.run(ctx)
            log.info("  ✓ %s (%.2fs)", stage.name, time.perf_counter() - t0)
        return ctx
