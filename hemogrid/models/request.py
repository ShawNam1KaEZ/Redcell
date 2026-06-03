from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import Field

from .common import CanonicalModel, Phenotype
from .enums import Component, Lever, RequestStatus

# Provenance guidance (set by the engine, not the loader):
#   All Request fields are DERIVED — Requests are created by the system,
#   not sourced from any external dataset.


class Request(CanonicalModel):
    request_id: str
    patient_id: str
    needed_by_date: date
    component: Component
    units: int = Field(ge=1)
    required_phenotype: Optional[Phenotype] = None
    # Ranked list of candidate donor_ids or bank_ids (best match first).
    candidate_matches: list[str] = Field(default_factory=list)
    chosen_lever: Optional[Lever] = None
    status: RequestStatus = RequestStatus.PREDICTED
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)
