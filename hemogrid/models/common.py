"""
Shared sub-models and the common base for all top-level canonical models.

CanonicalModel is the only place the `provenance` field is defined —
every canonical entity inherits it. Location, Phenotype, and Consent are
embedded sub-models (not canonical entities themselves) so they do not
carry provenance.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .enums import Provenance


class CanonicalModel(BaseModel):
    """
    Base class for all top-level canonical models.

    `provenance` maps each field name to its Provenance tag at the
    instance level, so two records of the same type can legitimately
    carry different tags (e.g. one donor's phenotype is PROVIDED because
    the organizer's sheet included it; another's is SYNTHETIC because we
    filled it in).  The UI uses this dict to render per-field tooltips.
    """

    model_config = ConfigDict(populate_by_name=True)

    provenance: dict[str, Provenance] = Field(default_factory=dict)


class Location(BaseModel):
    lat: float
    lng: float


class Phenotype(BaseModel):
    """Extended Rh (C, c, E, e) + Kell (K) antigen presence flags."""

    C: Optional[bool] = None
    c: Optional[bool] = None
    E: Optional[bool] = None
    e: Optional[bool] = None
    K: Optional[bool] = None


class Consent(BaseModel):
    contactable: bool
    channels: list[str] = Field(default_factory=list)
