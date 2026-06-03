from __future__ import annotations

from pydantic import BaseModel, Field

from .blood_bank import BloodBank
from .clinic import Clinic
from .donor import Donor
from .patient import Patient
from .request import Request


class CanonicalDataset(BaseModel):
    """
    Container returned by every DataSource.load() call.

    Holds all canonical entity lists together so callers receive one
    coherent snapshot rather than making separate calls per type.
    """

    patients: list[Patient] = Field(default_factory=list)
    donors: list[Donor] = Field(default_factory=list)
    blood_banks: list[BloodBank] = Field(default_factory=list)
    clinics: list[Clinic] = Field(default_factory=list)
    requests: list[Request] = Field(default_factory=list)
