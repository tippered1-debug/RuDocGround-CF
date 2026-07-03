"""Batched inference protocol implementations."""

from .compact import CompactBatchedProtocol
from .full import FullBatchedProtocol

__all__ = ["CompactBatchedProtocol", "FullBatchedProtocol"]
