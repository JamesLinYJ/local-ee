"""Lazy, narrowly typed IR for RF feature prediction and evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RFClassifiedFeatureTable:
    """Runtime table produced by predicting a bounded EE feature table."""

    source: Any
    classifier: Any
    spec: str
    columns: tuple[str, ...]
    row_count: int | None
    rows: str | None
    operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeRFTrainingConfusion:
    """Opaque resubstitution matrix produced from a trained Smile forest."""

    classifier: Any


@dataclass(frozen=True)
class RuntimeFeatureErrorMatrix:
    """Opaque matrix computed from an audited sampled or classified table."""

    table: Any
    spec: str


@dataclass(frozen=True)
class RuntimeConfusionValue:
    """One explicitly supported lazy accessor on a runtime confusion matrix."""

    matrix: RuntimeRFTrainingConfusion | RuntimeFeatureErrorMatrix
    spec: str
