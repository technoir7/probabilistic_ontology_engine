"""
POE_STRUCTURE_MODE configuration.

Two modes
---------
strict  (default)
    Standard BIC penalty (multiplier=1.0).  Production-calibrated thresholds.
    No behaviour change from the pre-diagnostic baseline.

explore
    Reduced BIC penalty (multiplier=0.25).  Relaxed pruning and wider explore
    band.  Intended for offline diagnostics and sensitivity analysis.
    Setting this mode ONLY affects the side-by-side ``bic_score_explore``
    field exposed by ``GET /v1/debug/structure`` — it does NOT change the
    live population manager which always uses multiplier=1.0.

Usage
-----
    from src.engine.config import get_structure_mode_config
    cfg = get_structure_mode_config()   # reads POE_STRUCTURE_MODE env var
    print(cfg.mode, cfg.bic_penalty_multiplier)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .schemas import EdgeExistenceThresholdConfig


@dataclass
class StructureModeConfig:
    """Parsed representation of the POE_STRUCTURE_MODE environment variable."""

    mode: str                        # "strict" | "explore"
    bic_penalty_multiplier: float    # used for side-by-side explore scoring
    min_evidence_before_pruning: int
    thresholds: EdgeExistenceThresholdConfig


# --- Preset configs -----------------------------------------------------------

_STRICT = StructureModeConfig(
    mode="strict",
    bic_penalty_multiplier=1.0,
    min_evidence_before_pruning=3,
    thresholds=EdgeExistenceThresholdConfig(
        prune_below=0.05,
        accept_above=0.90,
        explore_band=(0.3, 0.7),
    ),
)

_EXPLORE = StructureModeConfig(
    mode="explore",
    bic_penalty_multiplier=0.25,
    min_evidence_before_pruning=100,
    thresholds=EdgeExistenceThresholdConfig(
        prune_below=0.01,
        accept_above=0.95,
        explore_band=(0.15, 0.85),
    ),
)


def get_structure_mode_config() -> StructureModeConfig:
    """
    Read ``POE_STRUCTURE_MODE`` from the environment and return the
    corresponding ``StructureModeConfig``.  Defaults to ``strict``.

    Raises
    ------
    RuntimeError
        If the env var is set to an unrecognised value.
    """
    raw = os.environ.get("POE_STRUCTURE_MODE", "strict").strip().lower()
    if raw == "strict":
        return _STRICT
    if raw == "explore":
        return _EXPLORE
    raise RuntimeError(
        f"POE_STRUCTURE_MODE must be 'strict' or 'explore', got {raw!r}"
    )
