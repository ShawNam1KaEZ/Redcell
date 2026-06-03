"""
OrganizerAdapter — THE ONLY FILE EDITED ON HACKATHON DAY.

This adapter maps the organizer's unknown dataset columns to HemoGrid's
canonical models.  SyntheticSource (Phase 2) is the working implementation
used until then; this file remains a stub until the organizer's dataset
arrives.

On hackathon day, implement load() by:
  1. Reading the organizer-provided file (CSV / Excel / JSON — unknown until
     then).
  2. Mapping its columns to Patient / Donor / BloodBank / Clinic instances.
  3. Setting provenance tags accurately on each instance:
       PROVIDED  — field came directly from a source column
       DERIVED   — field was computed from source data (e.g. reliability_score)
       SYNTHETIC — field was fabricated (e.g. phenotype not in the organizer's data)
  4. Returning a CanonicalDataset.  The engine, agents, and UI never see the
     raw source — only the canonical objects this method emits.

Do NOT implement matching, forecasting, or enrichment logic here.  This file
maps columns; enrich() handles derivation.
"""
from __future__ import annotations

from ..models.dataset import CanonicalDataset
from .base import DataSource


class OrganizerAdapter(DataSource):
    @property
    def source_name(self) -> str:
        raise NotImplementedError(
            "OrganizerAdapter.source_name: set this to the organizer's dataset filename"
        )

    def load(self) -> CanonicalDataset:
        raise NotImplementedError(
            "OrganizerAdapter.load: implement on hackathon day by mapping the "
            "organizer's dataset columns to canonical models."
        )
