"""Compatibility wrapper for the compact batched protocol.

The implementation lives in :mod:`rudocground.runners`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runners.batched import run_batched
from .runners.protocols.compact import CompactBatchedProtocol


def run_variant_batched_compact(
    *,
    prompts_path: str | Path,
    gold_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    counterfactual_path: str | Path,
    manifest_path: str | Path,
    model: str = "qwen3:8b",
    base_url: str = "http://127.0.0.1:11434/api/chat",
    temperature: float = 0.0,
    seed: int = 42,
    keep_alive: str = "30m",
    resume: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    return run_batched(
        protocol=CompactBatchedProtocol(),
        prompts_path=prompts_path,
        gold_path=gold_path,
        output_path=output_path,
        report_path=report_path,
        counterfactual_path=counterfactual_path,
        manifest_path=manifest_path,
        model=model,
        base_url=base_url,
        default_num_ctx=4096,
        default_num_predict=1024,
        temperature=temperature,
        seed=seed,
        keep_alive=keep_alive,
        resume=resume,
        dry_run=dry_run,
    )


__all__ = ["run_variant_batched_compact"]
