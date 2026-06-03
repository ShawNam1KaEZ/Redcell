from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import Field

from .common import CanonicalModel, Consent, Location, Phenotype
from .enums import ABOGroup

# Provenance guidance (set by the loader, not the schema):
#   donor_id              → SYNTHETIC  (tokenized; no real identity in the system)
#   abo_group, rh_d       → PROVIDED or SYNTHETIC
#   phenotype             → PROVIDED if organizer includes it; else SYNTHETIC
#   location              → PROVIDED (geocoded) or SYNTHETIC
#   last_donation_date    → PROVIDED or SYNTHETIC
#   donation_count        → PROVIDED or DERIVED (from UCI Frequency)
#   reliability_score     → DERIVED  (computed from RFM; never provided raw)
#   consent               → SYNTHETIC (assumed for demo; real system requires explicit opt-in)
#   linked_patients       → DERIVED  (Blood Bridge bonds; built by the matching engine)
#   engagement_log        → DERIVED  (populated at runtime by the Engagement Agent)


class Donor(CanonicalModel):
    donor_id: str
    abo_group: ABOGroup
    rh_d: bool
    phenotype: Optional[Phenotype] = None
    location: Location
    last_donation_date: Optional[date] = None
    donation_count: int = Field(default=0, ge=0)
    reliability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    preferred_language: str
    consent: Consent
    linked_patients: list[str] = Field(default_factory=list)
    engagement_log: list[dict[str, Any]] = Field(default_factory=list)
