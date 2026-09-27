"""Typed errors that collectors catch to keep one failing category from
sinking the whole run. See aggregator.py for how these become
collection.errors[] / collection.category_status entries in the output.
"""
from __future__ import annotations


class CollectorError(Exception):
    """Base class for anything a category collector should catch and report,
    rather than let bubble up and kill the whole aggregation run."""

    def __init__(self, message: str, *, source: str | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.source = source
        self.code = code


class EndpointUnverifiedError(CollectorError):
    """Raised deliberately when a registry entry is `verified: false` and the
    caller asked to fail fast instead of attempting a possibly-wrong path."""


class UpstreamRequestError(CollectorError):
    """Network/HTTP failure talking to the platform or AppSec API."""


class GitOperationError(CollectorError):
    """Shelling out to `git` failed (clone, log, ls-tree, ...)."""
