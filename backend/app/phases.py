"""Development phases for a veterinary (companion-animal) medicine, and the value-inflection gates between them.

Phases follow the FDA CVM route (INAD file -> phased review of technical sections -> NADA, with conditional
approval under FD&C Act section 571 / GFI #261) and the EU route under Regulation (EU) 2019/6 (scientific advice,
centralised or national marketing authorisation; Art. 23 limited-market route for e.g. horses, not dogs or cats).
CMC and IP run in parallel with the studies; they are columns so the matrix shows them, not a strict sequence.

A "gate" marks a value-inflection point: the moment the asset is worth more because a risk has been retired, so a
go / no-go (and often a financing or partnering) decision belongs there.
"""

from __future__ import annotations

import re

SOURCES = [
    {"title": "FDA CVM: From an idea to the marketplace: the journey of an animal drug through the approval process",
     "url": "https://www.fda.gov/animal-veterinary/animal-health-literacy/idea-marketplace-journey-animal-drug-through-approval-process"},
    {"title": "FDA CVM GFI #261: Eligibility criteria for expanded conditional approval of new animal drugs",
     "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/cvm-gfi-261-eligibility-criteria-expanded-conditional-approval-new-animal-drugs"},
    {"title": "EMA: Veterinary limited markets (Regulation (EU) 2019/6, Art. 23)",
     "url": "https://www.ema.europa.eu/en/veterinary-regulatory-overview/research-development-veterinary-medicines/veterinary-limited-markets"},
]

# key, label (also the milestone "stage" value), short header, what happens, gate after this phase (None = no gate)
PHASES: list[dict] = [
    {"key": "discovery", "label": "Discovery and target validation", "short": "Discovery",
     "detail": "Target biology in the species and tumour type, hit finding, first in-vitro activity.", "gate": None},
    {"key": "lead", "label": "Lead optimization and candidate selection", "short": "Lead optimization",
     "detail": "Potency, selectivity, ADME and early tolerability; one development candidate (plus back-up) is nominated.",
     "gate": "Development candidate nominated"},
    {"key": "ip", "label": "Patent filing (provisional, then PCT)", "short": "Patent filing",
     "detail": "Composition-of-matter or use claims filed before public disclosure; PCT within 12 months; freedom-to-operate review.",
     "gate": "IP secured: asset becomes licensable"},
    {"key": "preclin", "label": "Preclinical pharmacology and target-species PK", "short": "Preclinical / PK",
     "detail": "Pharmacology, pilot toxicology, PK and dose finding in the target species (dog, cat or horse).", "gate": None},
    {"key": "cmc", "label": "CMC: API process, formulation and stability", "short": "CMC",
     "detail": "API route and specifications, final formulation, GMP pilot batches, stability; the CMC technical section.", "gate": None},
    {"key": "reg", "label": "Regulatory engagement (INAD, pre-submission conference, scientific advice)", "short": "INAD / advice",
     "detail": "Open the INAD file with FDA CVM, agree the technical-section plan and protocols (protocol concurrence); EMA scientific advice.",
     "gate": "Regulatory path agreed"},
    {"key": "tas", "label": "GLP target animal safety (TAS)", "short": "GLP safety (TAS)",
     "detail": "GLP margin-of-safety study in healthy target animals; supports the target animal safety technical section.",
     "gate": "Safety technical section complete"},
    {"key": "pilot", "label": "Pilot field efficacy (GCP) - proof of concept", "short": "Pilot efficacy (GCP)",
     "detail": "Small field study in client-owned patients under VICH GL9 GCP; first evidence of response.",
     "gate": "Clinical proof of concept: main partnering point"},
    {"key": "pivotal", "label": "Pivotal field effectiveness study (GCP)", "short": "Pivotal efficacy (GCP)",
     "detail": "Adequate and well-controlled field study under a concurred protocol; supports the effectiveness technical section.",
     "gate": "Pivotal readout"},
    {"key": "submission", "label": "Technical sections and NADA / EU marketing authorisation application", "short": "Dossier and filing",
     "detail": "Remaining technical sections (environmental, labeling, all other information), administrative NADA or EU application.", "gate": None},
    {"key": "approval", "label": "Approval (conditional or full) / marketing authorisation", "short": "Approval",
     "detail": "Full approval, or conditional approval on a reasonable expectation of effectiveness (renewable yearly, up to 5 years).",
     "gate": "Market authorisation"},
    {"key": "launch", "label": "Launch, scale-up and pharmacovigilance", "short": "Launch",
     "detail": "Commercial manufacturing, launch or out-licensing, adverse-event reporting; confirmatory data if conditionally approved.",
     "gate": None},
]

BY_KEY = {p["key"]: p for p in PHASES}
BY_LABEL = {p["label"]: p["key"] for p in PHASES}

# Earlier stage labels, kept so existing records still map.
LEGACY = {
    "Discovery": "discovery", "Candidate selection": "lead", "Feasibility / pilot target-animal studies": "pilot",
    "Pivotal target-animal safety": "tas", "Pivotal effectiveness (field) study": "pivotal", "CMC / manufacturing": "cmc",
    "Regulatory submission": "submission", "Approved / licensed (incl. conditional)": "approval", "Post-approval": "launch",
}

# Name keywords, checked in order (first match wins).
KEYWORDS: list[tuple[str, str]] = [
    (r"\b(patent|pct|provisional|freedom[- ]to[- ]operate|ip filing)\b", "ip"),
    (r"\b(inad|pre-?submission|protocol concurrence|scientific advice|regulatory meeting)\b", "reg"),
    (r"\b(glp|target[- ]animal safety|tas)\b", "tas"),
    (r"\bpivotal\b", "pivotal"),
    (r"\bpilot (field|efficacy|clinical)\b|\bproof of concept\b", "pilot"),
    (r"\b(pk|pharmacokinetic|pharmacology|dose[- ]finding|tox)\b", "preclin"),
    (r"\b(api|formulation|cmc|stability|gmp|batch)\b", "cmc"),
    (r"\b(nada|dossier|submission|technical section|marketing authori[sz]ation application|maa)\b", "submission"),
    (r"\b(approval|authori[sz]ation granted|licen[cs]ed)\b", "approval"),
    (r"\b(launch|pharmacovigilance|commerciali[sz]ation)\b", "launch"),
    (r"\bhit[- ]to[- ]lead\b|\b(target validation|screen(ing)?|hit)\b", "discovery"),
    (r"\b(lead|candidate)\b", "lead"),
]


def phase_of(name: str | None, stage: str | None) -> str | None:
    """Explicit phase label wins; otherwise the milestone name; otherwise an earlier stage label."""
    if stage in BY_LABEL:
        return BY_LABEL[stage]
    text = (name or "").lower()
    for pattern, key in KEYWORDS:
        if re.search(pattern, text):
            return key
    return LEGACY.get(stage or "")


def phase_map(programs: list[dict], milestones: list[dict]) -> dict:
    """Rows = pipelines, columns = phases. Each gate gets a state per pipeline: passed / next / ready / ahead (in order)."""
    order = [p["key"] for p in PHASES]
    rows = []
    for prog in programs:
        ms = [m for m in milestones if m["program_id"] == prog["id"] and m["status"] != "cancelled"]
        cells: dict[str, list] = {k: [] for k in order}
        for m in ms:
            key = phase_of(m["name"], m.get("stage"))
            cells[key or "discovery"].append({**m, "phase": key, "phase_inferred": m.get("stage") not in BY_LABEL})
        open_idx = [order.index(k) for k in order for m in cells[k] if m["status"] != "done"]
        done_idx = [order.index(k) for k in order for m in cells[k] if m["status"] == "done"]
        stage_key = phase_of(None, prog.get("stage"))
        current = min(open_idx) if open_idx else (max(done_idx) if done_idx else (order.index(stage_key) if stage_key else 0))
        gates = {}
        next_set = False
        for i, k in enumerate(order):
            if not BY_KEY[k]["gate"]:
                continue
            phase_open = any(m["status"] != "done" for m in cells[k])
            work_done = bool(cells[k]) and not phase_open
            # Gates pass in order: a gate cannot be passed while an earlier gate is still open.
            if not next_set and (work_done or (i < current and not phase_open)):
                gates[k] = "passed"
            elif not next_set:
                gates[k] = "next"
                next_set = True
            else:
                # e.g. a provisional patent filed before the candidate is nominated: the work is done,
                # but the gate's value only counts once every earlier gate has passed
                gates[k] = "ready" if work_done else "ahead"
        rows.append({"program_id": prog["id"], "code": prog["code"], "name": prog["name"], "status": prog["status"],
                     "current_phase": order[current], "cells": cells, "gates": gates})
    return {"phases": PHASES, "rows": rows, "sources": SOURCES,
            "note": "Phase of each milestone comes from its Stage field; if that is empty or an older label, it is inferred from the milestone name (marked 'inferred'). "
                    "Gates are value-inflection points where a go / no-go decision belongs. Gates pass in order: 'passed' needs every earlier gate passed; 'ready' means the phase's work is done but an earlier gate is still open."}
