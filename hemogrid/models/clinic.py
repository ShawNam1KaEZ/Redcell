from __future__ import annotations

from .common import CanonicalModel, Location

# Provenance guidance (set by the loader):
#   clinic_id  → PROVIDED or SYNTHETIC
#   location   → PROVIDED or SYNTHETIC
#   name       → PROVIDED or SYNTHETIC
#   region     → PROVIDED or SYNTHETIC


class Clinic(CanonicalModel):
    clinic_id: str
    location: Location
    name: str
    region: str
