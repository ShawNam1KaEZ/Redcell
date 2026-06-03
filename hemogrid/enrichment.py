"""
Indian population-frequency constants and synthetic-data generation helpers.

Every value produced here is tagged Provenance.SYNTHETIC.

Sources
-------
ABO / RhD:
    National Blood Transfusion Council India; pooled regional registry data.

Extended Rh + Kell (pooled from three large Indian donor phenotyping studies):
    · AIIMS Patna study           n = 10,032  donors
    · Gujarat donor survey        n =  5,670  donors
    · North India oncology study  n = 10,000  donors

Independence note
-----------------
Antigens are sampled INDEPENDENTLY by frequency.  This is an MVP
simplification.  Haplotype-based sampling (R1r, R2r, R0r, rr …) is the
biologically rigorous approach and is a documented future refinement.
"""
from __future__ import annotations

import numpy as np

from .models import ABOGroup, Phenotype

# ---------------------------------------------------------------------------
# Constants — single source of truth for Indian population frequencies
# ---------------------------------------------------------------------------

_ABO_GROUPS: list[ABOGroup] = [ABOGroup.O, ABOGroup.B, ABOGroup.A, ABOGroup.AB]
_ABO_PROBS:  list[float]    = [0.371,       0.322,       0.229,       0.078]

RHD_POS_PROB: float = 0.94   # P(RhD-positive); RhD-negative ≈ 0.06

# P(antigen PRESENT) in an Indian donor.
# K = 0.03 is the corrected Indian Kell frequency.
# The frequently-cited 0.09 figure is the Caucasian value — do NOT use it.
ANTIGEN_PRESENT_PROB: dict[str, float] = {
    "e": 0.985,   # near-universal
    "D": 0.940,   # same as RhD positive
    "C": 0.880,
    "c": 0.550,
    "E": 0.180,
    "K": 0.030,
}

# Rank-ordered clinical prevalence of alloantibodies in chronically transfused
# thalassemia patients (anti-K, anti-E, anti-c most common).
_ALLO_ANTIGENS: list[str]   = ["K",   "E",   "c",   "C",   "e"]
_ALLO_WEIGHTS:  list[float] = [0.35,  0.30,  0.20,  0.10,  0.05]

# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def random_abo_rh(rng: np.random.Generator) -> tuple[ABOGroup, bool]:
    """Sample ABO group and RhD status from Indian prevalence frequencies."""
    idx  = int(rng.choice(len(_ABO_GROUPS), p=_ABO_PROBS))
    rh_d = bool(rng.random() < RHD_POS_PROB)
    return _ABO_GROUPS[idx], rh_d


def random_phenotype(rng: np.random.Generator) -> Phenotype:
    """Sample Extended Rh + Kell antigens independently by frequency."""
    return Phenotype(
        C=bool(rng.random() < ANTIGEN_PRESENT_PROB["C"]),
        c=bool(rng.random() < ANTIGEN_PRESENT_PROB["c"]),
        E=bool(rng.random() < ANTIGEN_PRESENT_PROB["E"]),
        e=bool(rng.random() < ANTIGEN_PRESENT_PROB["e"]),
        K=bool(rng.random() < ANTIGEN_PRESENT_PROB["K"]),
    )


def generate_antibodies(
    phenotype: Phenotype,
    rng: np.random.Generator,
) -> list[str]:
    """
    Return 1–2 antibody strings for an ALREADY-ALLOIMMUNIZED individual.

    Correctness rule: a person CANNOT form an antibody against an antigen
    they carry.  This function enforces that rule — only antigens the person
    LACKS are eligible.  Call this only for alloimmunized individuals; the
    caller controls the rate (e.g. 20 % of thalassemia patients).
    """
    candidates:    list[str]   = []
    cand_weights:  list[float] = []

    for antigen, weight in zip(_ALLO_ANTIGENS, _ALLO_WEIGHTS):
        carries = getattr(phenotype, antigen, None)   # field name = antigen name
        if not carries:
            candidates.append(f"anti-{antigen}")
            cand_weights.append(weight)

    if not candidates:
        # Antigen-positive for all tracked antigens (rare); no antibody possible.
        return []

    total  = sum(cand_weights)
    probs  = [w / total for w in cand_weights]
    n      = 1 if rng.random() < 0.75 else min(2, len(candidates))
    idxs   = rng.choice(len(candidates), size=n, replace=False, p=probs)
    return [candidates[int(i)] for i in idxs]
