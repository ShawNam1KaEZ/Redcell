"""
DataSource contract.

Design choice — single load() vs. per-type methods:
    load() returns one CanonicalDataset rather than separate
    patients() / donors() / blood_banks() / ... methods.
    Reason: a source's entities are interdependent (e.g. Donor.clinic_id
    references a Clinic); loading them together keeps the snapshot
    consistent and the interface minimal — one call, one result.
    Callers unpack what they need from the container.

Two implementations:
    OrganizerAdapter  — edited on hackathon day (see organizer_adapter.py)
    SyntheticSource   — Phase 2; the working implementation used until then
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.dataset import CanonicalDataset


class DataSource(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable label used in logs and provenance traces."""
        ...

    @abstractmethod
    def load(self) -> CanonicalDataset:
        """
        Load all entities from this source and return them as a
        CanonicalDataset.  Implementations are responsible for running
        their data through enrich() and validate() before returning.
        """
        ...
