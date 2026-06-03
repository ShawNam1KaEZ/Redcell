from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import Field

from .common import CanonicalModel, Phenotype
from .enums import ABOGroup

# Provenance guidance (set by the loader, not the schema):
#   patient_id            → SYNTHETIC  (tokenized; no real ID enters the system)
#   abo_group, rh_d       → PROVIDED or SYNTHETIC
#   phenotype             → PROVIDED if the organizer includes it; else SYNTHETIC
#   known_antibodies      → PROVIDED or SYNTHETIC
#   transfusion_interval_days, units_per_session → SYNTHETIC (clinically plausible range)
#   last_transfusion_date → PROVIDED or SYNTHETIC
#   clinic_id             → PROVIDED or SYNTHETIC


class Patient(CanonicalModel):
    patient_id: str
    abo_group: ABOGroup
    rh_d: bool
    phenotype: Optional[Phenotype] = None
    known_antibodies: list[str] = Field(default_factory=list)
    transfusion_interval_days: int = Field(ge=21, le=28)
    last_transfusion_date: date
    units_per_session: int = Field(ge=1, le=2)
    clinic_id: str
    preferred_language: str
