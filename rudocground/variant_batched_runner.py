"""Compatibility wrapper for the full batched protocol.

The implementation lives in :mod:`rudocground.runners`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .runners.batched import run_batched
from .runners.protocols.full import FullBatchedProtocol


def run_variant_batched(
    *,
    prompts_path: str | Path,
    gold_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    counterfactual_path: str | Path,
    manifest_path: str | Path,
    model: str = "qwen3:8b",
    base_url: str = "http://127.0.0.1:11434/api/chat",
    num_ctx: int = 16384,
    num_predict: int = 4096,
    temperature: float = 0.0,
    seed: int = 42,
    keep_alive: str = "30m",
    resume: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    return run_batched(
        protocol=FullBatchedProtocol(),
        prompts_path=prompts_path,
        gold_path=gold_path,
        output_path=output_path,
        report_path=report_path,
        counterfactual_path=counterfactual_path,
        manifest_path=manifest_path,
        model=model,
        base_url=base_url,
        default_num_ctx=num_ctx,
        default_num_predict=num_predict,
        temperature=temperature,
        seed=seed,
        keep_alive=keep_alive,
        resume=resume,
        dry_run=dry_run,
    )


__all__ = ["run_variant_batched"]
