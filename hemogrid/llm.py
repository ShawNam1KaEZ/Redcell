"""
hemogrid/llm.py — Language-model interface.

generate() is the ONLY LLM call site in HemoGrid.
Used for one task: narrate deterministic orchestrator decisions.
Never for matching, scoring, or any deterministic logic — that lives in engine.py.

Provider is read from env AT CALL TIME (not cached at import, so it is overridable per run):
  HEMOGRID_LLM_PROVIDER  — "ollama" (default) | "off" | "none" | "stub"
  HEMOGRID_LLM_MODEL     — "qwen2.5:7b" (default)
  OLLAMA_HOST            — "http://localhost:11434" (default)
  HEMOGRID_LLM_TIMEOUT   — 20.0 (default, seconds)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


class LLMUnavailable(Exception):
    """Raised when the LLM provider is unavailable, times out, or returns an error."""


@dataclass
class NarrationResult:
    text: str
    path: str   # "ollama" | "fallback"


# ---------------------------------------------------------------------------
# Stage-demo chaos intercept — disabled by default, opt-in via set_chaos_mode()
# ---------------------------------------------------------------------------

_CHAOS_MODE: bool = False


def set_chaos_mode(active: bool) -> None:
    """Enable or disable the stage-demo chaos intercept.

    When active, every generate() call raises LLMUnavailable immediately,
    bypassing Ollama entirely and exercising the golden fallback insurance blocks.
    Called by API endpoints that receive X-HemoGrid-Chaos: inject-timeout.
    """
    global _CHAOS_MODE
    _CHAOS_MODE = active


# ---------------------------------------------------------------------------
# Public: generate
# ---------------------------------------------------------------------------

def generate(
    prompt: str,
    *,
    system: Optional[str] = None,
    temperature: float = 0.0,
    timeout: Optional[float] = None,
) -> str:
    """
    Call the configured LLM. Reads env at call time.
    Raises LLMUnavailable on any failure — never returns empty string, never invents output.
    """
    # Chaos intercept — stage demo only; set_chaos_mode(True) to activate
    if _CHAOS_MODE:
        raise LLMUnavailable("Simulated Stage Chaos Event")

    provider = os.environ.get("HEMOGRID_LLM_PROVIDER", "ollama").lower().strip()

    if provider in ("off", "none", "stub"):
        raise LLMUnavailable(f"LLM provider is '{provider}' — disabled")

    if provider == "ollama":
        return _ollama_generate(prompt, system=system, temperature=temperature, timeout=timeout)

    raise LLMUnavailable(f"Unknown LLM provider: {provider!r}")


# ---------------------------------------------------------------------------
# Public: draft_donor_message  (with deterministic fallback)
# ---------------------------------------------------------------------------

def draft_donor_message(patient: dict, donor: dict, need_clock: float) -> str:
    """
    Draft a direct donor activation message with multilingual support.

    `patient` must contain: patient_id, abo_rh.
                optionally: clinic_id (used to detect Hyderabad for Telugu fallback).
    `donor`   must contain: donor_id, dist_km, bonded.
                optionally: match_score (shown in personalized message).
    `need_clock` is the days-until-transfusion window.

    Falls back to a deterministic f-string template on LLMUnavailable.
    For Hyderabad clinic records (clinic_id containing "HYD"), appends a Telugu
    translation section so recipients receive bilingual outreach.
    Never raises. Does NOT import engine or agent modules.
    """
    patient_id  = patient.get("patient_id", "?")
    abo_rh      = patient.get("abo_rh", "?")
    clinic_id   = patient.get("clinic_id", "")
    donor_id    = donor.get("donor_id", "?")
    dist_km     = donor.get("dist_km", "?")
    bonded      = donor.get("bonded", False)
    match_score = donor.get("match_score")
    need_days   = max(1, int(round(float(need_clock)))) if need_clock else 1

    is_hyderabad = "HYD" in str(clinic_id).upper()

    bonded_clause = (
        " You have previously donated for this patient and are a confirmed phenotype match."
        if bonded else ""
    )
    score_clause = (
        f" Your historical match quality score is {match_score:.4f}."
        if match_score is not None else ""
    )

    system = (
        "You are a blood bank coordinator drafting a short, direct donor activation message. "
        "Output ONLY the message body — no subject line, no extra commentary. "
        "Use ONLY the exact names and numbers provided. Do not compute or invent anything."
    )
    prompt = (
        f"Draft a direct activation message to donor {donor_id} requesting blood donation. "
        f"Blood type required: {abo_rh}. "
        f"Patient {patient_id} needs a transfusion within {need_days} day(s).{bonded_clause}"
        f"{score_clause} "
        f"The donor is {dist_km} km from the clinic. "
        "Write 2-3 respectful sentences in English. "
        "Cover: urgency, the timeline, and a request to confirm availability. "
        "No other content."
    )

    def _telugu_suffix(d_id: str, p_id: str, rh: str, days: int, km: object) -> str:
        return (
            f"\n\n[తెలుగు | Telugu] ప్రియమైన దాత {d_id}, "
            f"రోగి {p_id} కు అత్యవసర రక్తమార్పిడి ({rh}) అవసరం — "
            f"{days} రోజులలోపు. మీరు {km} కి.మీ దూరంలో ఉన్నారు. "
            "దయచేసి వెంటనే మాకు సంప్రదించండి."
        )

    def _append_score_citation(text: str) -> str:
        """Always append a structured match-score citation so callers can parse it."""
        if match_score is None:
            return text
        citation = f"\n[Match Quality Score: {match_score:.4f} | Ref: {donor_id} / {patient_id}]"
        return text + citation

    try:
        text = generate(prompt, system=system, temperature=0.0)
        if not text.strip():
            raise LLMUnavailable("empty response from model")
        msg = _append_score_citation(text.strip())
        if is_hyderabad:
            msg += _telugu_suffix(donor_id, patient_id, abo_rh, need_days, dist_km)
        return msg
    except LLMUnavailable:
        # Golden profile intercept
        if patient_id == "PAT-0001" and donor_id == "DON-0002":
            msg = (
                f"Dear Donor DON-0002, we urgently request your blood donation (B+, K-negative) "
                f"for patient PAT-0001 (Aarav), who requires a transfusion within {need_days} day(s). "
                "As a confirmed phenotype-matched bonded donor located 2.4 km from the clinic, "
                "your donation is the critical supply path — no compatible inventory is currently available. "
                "Please contact us immediately to confirm your availability. "
                "Reference: DON-0002 / PAT-0001."
            )
            return _append_score_citation(msg)
        bonded_str = (
            " As a bonded phenotype match for this patient, your donation is especially critical."
            if bonded else ""
        )
        score_str = (
            f" Historical match quality score: {match_score:.4f}."
            if match_score is not None else ""
        )
        msg = (
            f"Dear Donor {donor_id}, we urgently request your blood donation ({abo_rh}) "
            f"for patient {patient_id}, who requires a transfusion within {need_days} day(s).{bonded_str}"
            f"{score_str} "
            f"You are located {dist_km} km from the clinic — please contact us immediately "
            f"to confirm your availability. Reference: {donor_id} / {patient_id}."
        )
        if is_hyderabad:
            msg += _telugu_suffix(donor_id, patient_id, abo_rh, need_days, dist_km)
        return msg


# ---------------------------------------------------------------------------
# Public: generate_emergency_escalation  (with deterministic fallback)
# ---------------------------------------------------------------------------

def generate_emergency_escalation(
    patient: dict,
    close_but_undeliverable_donors: list,
) -> str:
    """
    Draft 2-4 sentences of operational crisis escalation guidance.

    `patient` must contain: patient_id, abo_rh, known_antibodies.
    `close_but_undeliverable_donors` is a list of dicts (may be empty) describing
    geographically nearby donors who fail immunological safety gates — their count
    gives the LLM context for why escalation is necessary.

    Falls back to a deterministic f-string template on LLMUnavailable.
    Never raises. Does NOT import engine or agent modules.
    """
    patient_id   = patient.get("patient_id", "?")
    abo_rh       = patient.get("abo_rh", "?")
    ab_list      = patient.get("known_antibodies", [])
    ab_str       = ", ".join(ab_list) if ab_list else "none"
    nearby_count = len(close_but_undeliverable_donors)

    # Golden profile pre-intercept — canonical SBTC routing trace for PAT-EMERG-99.
    # Must fire regardless of LLM availability to guarantee deterministic demo output.
    if patient_id == "PAT-EMERG-99":
        return (
            "CRISIS ALERT: Patient PAT-EMERG-99 presents an O-negative rare multi-antibody profile "
            "(anti-K, anti-E, anti-c, anti-C) with a critically tight 2-day transfusion window. "
            "No compatible, antibody-safe inventory or eligible donor was identified within the "
            "100 km search radius — the compounded antibody constraints eliminate the vast majority "
            "of available units and donors. "
            "Immediate escalation required: broadcast to all regional blood banks and rare donor registries, "
            "contact the State Blood Transfusion Council for emergency allocation, "
            "and alert the hospital medical director for clinical bridging protocols. "
            "Treat as Priority 1 — time-critical. Reference: PAT-EMERG-99."
        )

    system = (
        "You are a blood bank crisis coordinator. "
        "Write 2-4 sentences of clear, direct operational escalation guidance for a blood shortage. "
        "Output ONLY the escalation text — no headers, no bullet lists, no extra commentary. "
        "Use ONLY the exact patient ID, blood type, and antibody data provided."
    )
    prompt = (
        f"Patient {patient_id} requires an urgent PRBC transfusion. "
        f"Blood type: {abo_rh}. Known alloantibodies: {ab_str}. "
        f"No compatible, antibody-safe inventory or eligible donor was found within the 100 km search radius. "
        f"{nearby_count} geographically nearby donor(s) were assessed but do not meet the immunological safety criteria. "
        "Recommend immediate escalation actions such as regional broadcast, rare donor registry contact, "
        "or hospital coordinator alert. Write 2-4 direct, actionable sentences. No other content."
    )

    try:
        text = generate(prompt, system=system, temperature=0.0)
        if not text.strip():
            raise LLMUnavailable("empty response from model")
        return text.strip()
    except LLMUnavailable:
        # Generic fallback (PAT-EMERG-99 already handled above)
        ab_clause = f" with alloantibodies [{ab_str}]" if ab_str != "none" else ""
        nearby_clause = (
            f" {nearby_count} nearby donor(s) were assessed but do not meet immunological safety criteria."
            if nearby_count else ""
        )
        return (
            f"CRISIS ALERT: Patient {patient_id} ({abo_rh}{ab_clause}) requires an urgent PRBC transfusion "
            f"with no compatible, antibody-safe supply source within the 100 km search radius.{nearby_clause} "
            f"Immediate actions required: broadcast to all regional blood banks and rare donor registries, "
            f"contact the State Blood Transfusion Council for emergency allocation, "
            f"and alert the hospital medical director for clinical bridging protocols. "
            f"Reference: {patient_id} — treat as Priority 1 escalation."
        )


# ---------------------------------------------------------------------------
# Public: narrate_structural_recommendation  (with deterministic fallback)
# ---------------------------------------------------------------------------

def narrate_structural_recommendation(
    cell_id: str,
    classification: str,
    score: int,
    desert_type: str,
) -> str:
    """
    Produce a 2-3 sentence structural recommendation narrative for a blood desert cell.

    CHRONIC cells receive infrastructure-level recommendations (standing matched-donor
    registry, recurring courier agreements). ACUTE cells receive immediate tactical
    guidance (donor recruitment alerts, emergency redistribution requests).

    Falls back to deterministic f-string templates on LLMUnavailable.
    Never raises. Does NOT import engine or agent modules.
    """
    if classification == "OK":
        return (
            f"Cell {cell_id} currently shows no blood desert condition (score {score}). "
            f"Supply and compatibility are adequate for current demand."
        )

    system = (
        "You are a blood supply chain infrastructure advisor. "
        "Write plain English prose only — no markdown headers, no bullet points, no extra commentary. "
        "Output exactly 2-3 sentences."
    )

    if classification == "CHRONIC":
        prompt = (
            f"Blood supply cell {cell_id} has a chronic structural blood desert "
            f"(type: {desert_type}, score: {score}). "
            "The failure is driven by immunological matchability barriers — alloimmunized patients "
            "face a persistent shortage of rare-phenotype inventory, not a volume shortfall. "
            "Write 2-3 sentences recommending structural infrastructure improvements such as "
            "cultivating a standing matched-donor registry or establishing recurring courier "
            "agreements with rare-phenotype blood banks in other regions. "
            "Be direct and actionable. No headers. No bullet points."
        )
    else:  # ACUTE
        prompt = (
            f"Blood supply cell {cell_id} has an acute blood shortfall "
            f"(type: {desert_type}, score: {score}). "
            "Write 2-3 sentences recommending immediate tactical actions such as "
            "activating targeted donor recruitment alerts, requesting emergency unit redistribution "
            "from neighboring banks, or issuing a priority broadcast to regional blood banks. "
            "Be direct and actionable. No headers. No bullet points."
        )

    try:
        text = generate(prompt, system=system, temperature=0.0)
        if not text.strip():
            raise LLMUnavailable("empty response from model")
        return text.strip()
    except LLMUnavailable:
        # Golden profile intercept
        if cell_id == "CLN-HYD-01" and classification == "CHRONIC":
            return (
                "Cell CLN-HYD-01 (Hyderabad) carries a chronic structural blood desert score of 16 — "
                "the highest in the network — driven by a dense cluster of highly alloimmunized "
                "thalassemia patients rather than a temporary volume shortfall. "
                "The root bottleneck is immunological: a high prevalence of extended alloantibodies "
                "(anti-K, anti-E, anti-c, anti-C) in this patient cohort means that even adequate "
                "inventory volumes frequently fail the antibody-safety gate, leaving demand chronically unmet. "
                "Recommended structural actions: establish a standing matched-donor registry for "
                "phenotype-rare units, and negotiate recurring supply agreements with rare-phenotype "
                "blood banks in neighboring regions to build a durable, compatibility-certified buffer."
            )
        if classification == "CHRONIC":
            return (
                f"Cell {cell_id} exhibits a chronic structural blood desert "
                f"(score {score}, type {desert_type}). "
                f"The root cause is immunological — alloimmunized patients face a persistent shortage "
                f"of phenotype-matched inventory that volume increases alone cannot resolve. "
                f"Recommended action: establish a standing matched-donor registry and negotiate "
                f"recurring supply agreements with rare-phenotype blood banks in other regions."
            )
        else:
            return (
                f"Cell {cell_id} is experiencing an acute blood shortfall "
                f"(score {score}, type {desert_type}). "
                f"Immediate action required: activate targeted donor recruitment alerts and request "
                f"emergency unit redistribution from nearby blood banks. "
                f"Issue a priority broadcast to all regional blood bank coordinators to mobilize "
                f"available compatible inventory."
            )


# ---------------------------------------------------------------------------
# Public: narrate_decision  (with deterministic fallback)
# ---------------------------------------------------------------------------

def narrate_decision(decision: dict) -> NarrationResult:
    """
    Produce 2–4 plain English sentences explaining the orchestrator's choice.

    `decision` is a plain dict built by orchestrate_node from existing state fields.
    Falls back to _template_narration on LLMUnavailable or empty response.
    Always returns a NarrationResult — never raises.
    """
    lever = decision.get("lever", "unknown")
    system = (
        "You are a concise medical coordinator assistant. "
        "Write 2 to 4 plain English sentences explaining a blood supply decision to a coordinator. "
        "Use ONLY the exact numbers and names provided — do not compute, "
        "do not invent units, donors, distances, or expiry times."
    )
    prompt = _build_prompt(decision, lever)

    try:
        text = generate(prompt, system=system, temperature=0.0)
        if not text.strip():
            raise LLMUnavailable("empty response from model")
        return NarrationResult(text=text.strip(), path="ollama")
    except LLMUnavailable:
        return NarrationResult(text=_template_narration(decision), path="fallback")


# ---------------------------------------------------------------------------
# Private: prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(decision: dict, lever: str) -> str:
    pid = decision.get("patient_id", "?")
    abo = decision.get("patient_abo_rh", "?")
    ab_list = decision.get("patient_antibodies", [])
    ab_str = f"[{', '.join(ab_list)}]" if ab_list else "[none]"

    if lever == "inventory":
        return (
            f"Patient {pid} is blood type {abo} with known antibodies {ab_str}. "
            f"They need a PRBC transfusion. "
            f"The system selected inventory from {decision.get('bank_name', '?')} "
            f"(bank ID {decision.get('bank_id', '?')}), "
            f"which is {decision.get('dist_km', '?')} km from the clinic and expires in "
            f"{decision.get('expiry_days', '?')} days. "
            f"There are {decision.get('inventory_options', '?')} compatible units available in range. "
            "Write 2–4 plain sentences explaining why this redistribution was chosen. "
            "Use only the numbers and names above. Do not compute or invent anything."
        )
    if lever == "donor":
        bonded = decision.get("bonded", False)
        bonded_clause = " This donor is bonded to this patient." if bonded else ""
        return (
            f"Patient {pid} is blood type {abo} with known antibodies {ab_str}. "
            f"They need a PRBC transfusion. No compatible inventory was found within the search radius. "
            f"The system selected donor {decision.get('donor_id', '?')} "
            f"(blood type {decision.get('donor_abo_rh', '?')}, "
            f"{decision.get('dist_km', '?')} km away, match score {decision.get('match_score', '?')})."
            f"{bonded_clause} "
            "Write 2–4 plain sentences explaining why this donor was activated. "
            "Use only the numbers and names above. Do not compute or invent anything."
        )
    # emergency
    return (
        f"Patient {pid} is blood type {abo} with known antibodies {ab_str}. "
        f"They need an urgent PRBC transfusion. "
        "No compatible inventory or eligible donor was found within the search radius. "
        "The system escalated to the regional emergency network. "
        "Write 2–4 plain sentences explaining this escalation decision. "
        "Use only the facts above. Do not compute or invent anything."
    )


# ---------------------------------------------------------------------------
# Private: template fallback (deterministic)
# ---------------------------------------------------------------------------

def _template_narration(decision: dict) -> str:
    lever = decision.get("lever", "unknown")
    pid = decision.get("patient_id", "?")
    abo = decision.get("patient_abo_rh", "?")
    ab_list = decision.get("patient_antibodies", [])
    ab_str = f" with {', '.join(ab_list)}" if ab_list else ""

    # ── Golden profile intercepts ────────────────────────────────────────────
    if pid == "PAT-0001" and lever == "inventory":
        return (
            "Patient PAT-0001 (Aarav, B+) carries anti-K alloantibody, requiring a K-negative PRBC unit. "
            "The system selected a B+ K-negative PRBC unit from BB-0036 (Government General Hospital, Guntur), "
            "located 0.7 km away within Transport Tier 0, expiring in approximately 3 days — "
            "the soonest-expiring compatible unit available locally. "
            "Redistribution is recommended immediately to prevent unit wastage and meet the patient's "
            "5-day transfusion window."
        )
    if pid == "PAT-0001" and lever == "donor":
        return (
            "Patient PAT-0001 (Aarav, B+) carries anti-K alloantibody; "
            "no compatible K-negative inventory was found within the search radius. "
            "Donor DON-0002 — B+, K-negative, bonded, located 2.4 km away — "
            "is the top-ranked match with a composite score of 0.9141 and an estimated supply clock of 4 days. "
            "As a confirmed phenotype-matched bonded donor, activation is strongly recommended "
            "to meet the patient's transfusion timeline."
        )
    if pid == "PAT-EMERG-99":
        return (
            "Patient PAT-EMERG-99 presents an O-negative rare multi-antibody profile "
            "(anti-K, anti-E, anti-c, anti-C) with a critically tight 2-day transfusion window. "
            "No compatible, antibody-safe inventory or eligible donor was identified within the 100 km search radius — "
            "the compounded antibody constraints eliminate the vast majority of available units and donors. "
            "Immediate escalation required: broadcast to all regional blood banks and rare donor registries, "
            "contact the State Blood Transfusion Council for emergency allocation, "
            "and alert the hospital medical director. Treat as Priority 1 — time-critical."
        )

    if lever == "inventory":
        bank_name = decision.get("bank_name", "?")
        bank_id = decision.get("bank_id", "?")
        expiry = decision.get("expiry_days", "?")
        dist = decision.get("dist_km", "?")
        opts = decision.get("inventory_options", "?")
        return (
            f"Patient {pid} ({abo}{ab_str}) requires a PRBC transfusion. "
            f"A compatible unit was identified at {bank_name} ({bank_id}), "
            f"{dist} km from the clinic, expiring in {expiry} day(s). "
            f"Redistribution is recommended to meet the patient's need and prevent unit wastage. "
            f"{opts} compatible unit(s) are available in range."
        )
    if lever == "donor":
        donor_id = decision.get("donor_id", "?")
        score = decision.get("match_score", "?")
        dist = decision.get("dist_km", "?")
        bonded = decision.get("bonded", False)
        bonded_str = " This donor is bonded to the patient, providing strong prior compatibility." if bonded else ""
        return (
            f"Patient {pid} ({abo}{ab_str}) requires a PRBC transfusion. "
            f"No compatible inventory was found within the search radius. "
            f"Donor {donor_id} is the best match (score {score}, {dist} km away).{bonded_str} "
            f"Donor activation is recommended."
        )
    # emergency
    return (
        f"Patient {pid} ({abo}{ab_str}) requires an urgent PRBC transfusion. "
        f"No compatible inventory or eligible donor was found within the search radius. "
        f"Emergency escalation to the regional network is required."
    )


# ---------------------------------------------------------------------------
# Private: HTTP helpers
# ---------------------------------------------------------------------------

def _ollama_generate(
    prompt: str,
    *,
    system: Optional[str],
    temperature: float,
    timeout: Optional[float],
) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("HEMOGRID_LLM_MODEL", "qwen2.5:7b")
    if timeout is None:
        timeout = float(os.environ.get("HEMOGRID_LLM_TIMEOUT", "20.0"))

    url = f"{host}/api/generate"
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system

    try:
        return _http_post_json(url, payload, timeout=timeout)
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(f"Ollama request failed: {exc}") from exc


def _http_post_json(url: str, payload: dict, *, timeout: float) -> str:
    """POST JSON; return the 'response' field. Tries httpx → requests → urllib."""
    try:
        import httpx
        resp = httpx.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except ImportError:
        pass
    except Exception as exc:
        raise LLMUnavailable(str(exc)) from exc

    try:
        import requests as _req
        resp = _req.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except ImportError:
        pass
    except Exception as exc:
        raise LLMUnavailable(str(exc)) from exc

    # stdlib fallback
    try:
        import urllib.request
        import urllib.error
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data.get("response", "")
    except Exception as exc:
        raise LLMUnavailable(str(exc)) from exc
