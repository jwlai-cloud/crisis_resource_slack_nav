"""Typed core for the Crisis Resource Navigator (design doc §6).

The agent stays mostly stateless and leans on the workspace as its store, but a
thin typed index makes need <-> offer ranking fast and drives the coordinator
Canvas. These models are that index's value type.
"""

from .models import (
    PROJECT_NAMESPACE,
    Need,
    Offer,
    Resolution,
    Status,
    Urgency,
    deterministic_id,
)

__all__ = [
    "PROJECT_NAMESPACE",
    "Need",
    "Offer",
    "Resolution",
    "Status",
    "Urgency",
    "deterministic_id",
]
