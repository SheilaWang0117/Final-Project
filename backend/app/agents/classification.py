"""Pipeline Classification Agent: description -> proposed structured profile.

The proposal is never applied automatically; the user reviews, corrects, and
confirms it. Evidence quotes are checked against the description: a quote that
does not appear verbatim is removed and the field is downgraded.
"""

from __future__ import annotations

import re

from .common import Deps, is_verbatim, make_agent, mode
from .runner import Recorder, finish_ok, record_demo_run, run_agent, untrusted_block
from .schemas import ClassificationProposal, FieldProposal, ListFieldProposal

JURIS = {"US": ["us", "u.s.", "united states", "america", "usa", "fda"], "EU": ["eu", "europe", "european"], "CN": ["china", "chinese", "prc", "mainland"],
         "JP": ["japan", "japanese"], "KR": ["korea", "korean"], "HK": ["hong kong"], "UK": ["uk", "united kingdom", "britain"]}


ZH_QUESTIONS = {
    "What molecular target(s) does the program address?": "该项目针对哪些分子靶点？",
    "Which specific tumor type or indication is intended first?": "首先针对哪种具体肿瘤类型或适应症？",
    "What route of administration is planned?": "计划采用哪种给药途径？",
}
ZH_CAUTION = ("简短描述不能确定监管路径。美国兽用抗体由 FDA CVM 还是 USDA CVB 监管，取决于作用机制和宣称用途，需要与监管机构确认；"
              "中国兽药由农业农村部（MARA）而非国家药监局（NMPA）监管。")


def verify(proposal: ClassificationProposal, description: str) -> tuple[dict, list[str]]:
    """Drop non-verbatim evidence; downgrade unsupported 'stated' fields."""
    notes = []
    data = proposal.model_dump()
    for name, f in data.items():
        if not isinstance(f, dict) or "evidence" not in f:
            continue
        kept = [q for q in f["evidence"] if is_verbatim(q, description)]
        dropped = len(f["evidence"]) - len(kept)
        if dropped:
            notes.append(f"{name}: removed {dropped} quote(s) not found verbatim in the description")
        f["evidence"] = kept
        if f["status"] == "stated" and not kept:
            f["status"] = "inferred"
            notes.append(f"{name}: marked 'inferred' because no verbatim evidence supports 'stated'")
        if name == "jurisdictions":
            f["value"] = [j for j in f["value"] if j in ("US", "EU", "CN", "JP", "KR", "HK", "UK", "Other")]
        if name == "use_type" and f["value"] not in ("human", "veterinary", "unknown", None):
            f["value"] = "unknown"
        if name == "molecule_category" and f["value"] not in ("small_molecule", "biologic", "other", "unknown", None):
            f["value"] = "unknown"
    return data, notes


def _field(value, status, evidence, explanation):
    return FieldProposal(value=value, status=status, evidence=evidence, explanation=explanation)


def rule_based(description: str) -> ClassificationProposal:
    """Deterministic demo classifier (no model). Clearly labeled as rule-based."""
    low = description.lower()

    def find(*words):
        for w in words:
            m = re.search(rf"\b{re.escape(w)}\w*", low)
            if m:
                return description[m.start():m.end()]
        return None

    species, sev = [], []
    for words, sp in ((("canine", "dog"), "dog"), (("feline", "cat"), "cat"), (("equine", "horse"), "horse")):
        q = find(*words)
        if q:
            species.append(sp)
            sev.append(q)
    human_q = find("patient", "human")
    use = "veterinary" if species or find("veterinary") else "human" if human_q else "unknown"
    mod_q = find("bispecific", "monoclonal", "antibod", "adc", "car-t", "vaccine", "gene therapy", "plasmid", "small molecule", "peptide", "protein")
    modality = None
    if mod_q:
        m = mod_q.lower()
        modality = "bispecific antibody" if "bispecific" in m else "monoclonal antibody" if ("monoclonal" in m or "antibod" in m) else mod_q
    cat = "biologic" if modality and any(k in modality.lower() for k in ("antibod", "protein", "vaccine", "gene", "plasmid", "car")) else "small_molecule" if modality and "small" in modality.lower() else "unknown"
    onc_q = find("oncology", "cancer", "tumor", "tumour", "lymphoma", "osteosarcoma", "carcinoma", "melanoma", "mast cell")
    juris, jev = [], []
    for code, words in JURIS.items():
        for w in words:
            m = re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low)
            if m:
                juris.append(code)
                jev.append(description[m.start():m.end()])
                break
    questions = []
    if not find("target", "anti-", "pd-1", "her2", "cd20", "egfr"):
        questions.append("What molecular target(s) does the program address?")
    if not find("lymphoma", "osteosarcoma", "carcinoma", "melanoma", "mast cell", "hemangiosarcoma"):
        questions.append("Which specific tumor type or indication is intended first?")
    if not find("intravenous", "subcutaneous", "oral", "topical", "iv ", "injection"):
        questions.append("What route of administration is planned?")
    return ClassificationProposal(
        use_type=_field(use, "stated" if species or human_q else "unknown", sev[:1] or ([human_q] if human_q else []), "Rule-based: species words imply veterinary use."),
        species=ListFieldProposal(value=species, status="stated" if species else "unknown", evidence=sev[:3], explanation="Matched species keywords."),
        therapeutic_area=_field("oncology" if onc_q else None, "stated" if onc_q else "unknown", [onc_q] if onc_q else [], "Matched oncology keywords." if onc_q else "Not stated."),
        indication=_field(None, "unknown", [], "No specific tumor type found; please specify."),
        modality=_field(modality, "stated" if modality else "unknown", [mod_q] if mod_q else [], "Matched modality keywords." if modality else "Not stated."),
        molecule_category=_field(cat, "inferred" if cat != "unknown" else "unknown", [mod_q] if mod_q else [], "Antibodies and proteins are biologics." if cat == "biologic" else "Not determinable."),
        target=_field(None, "unknown", [], "Target not stated."),
        mechanism=_field(None, "unknown", [], "Mechanism not stated."),
        route=_field(None, "unknown", [], "Route not stated."),
        jurisdictions=ListFieldProposal(value=juris, status="stated" if juris else "unknown", evidence=jev[:4], explanation="Matched place names." if juris else "No jurisdictions mentioned."),
        suggested_stage_template="veterinary" if use == "veterinary" else "human",
        follow_up_questions=questions[:5],
        public_search_terms=[t for t in [f"{'canine' if 'dog' in species else 'feline' if 'cat' in species else ''} {modality or ''}".strip(), f"{'canine' if 'dog' in species else 'feline' if 'cat' in species else ''} oncology".strip() if onc_q else ""] if t],
        regulatory_caution="A short description does not establish a regulatory pathway. For veterinary antibodies in the US, jurisdiction (FDA CVM vs USDA CVB) depends on mechanism and claims and needs agency confirmation; China veterinary products fall under MARA, not NMPA.",
    )


async def classify(description: str, *, model=None, language: str = "en") -> dict:
    rec = Recorder("classification", mode() if model is None else "test")
    if rec.mode == "demo":
        proposal = rule_based(description)
        if language == "zh":
            proposal.follow_up_questions = [ZH_QUESTIONS.get(q, q) for q in proposal.follow_up_questions]
            proposal.regulatory_caution = ZH_CAUTION
        data, notes = verify(proposal, description)
        run = record_demo_run("classification", rec, "Rule-based demo classifier; no model call.")
        return {"proposal": data, "verification_notes": notes, "method": "rule_based_demo", "run": run}
    agent = make_agent("classification", ClassificationProposal, model=model)
    prompt = "Classify this program description. It was typed by the user.\n" + untrusted_block("user_description", description)
    if language == "zh":
        prompt += ("\nWrite every `explanation`, the follow-up questions and the regulatory caution in Simplified Chinese. "
                   "Keep field values in English (for example 'veterinary', 'biologic', 'dog', 'US') and keep evidence quotes exactly as written by the user.")
    output = await run_agent(agent, prompt, deps=Deps(rec=rec), rec=rec)
    data, notes = verify(output, description)
    rec.step("verify_evidence", {"notes": notes})
    run = finish_ok(rec)
    return {"proposal": data, "verification_notes": notes, "method": "llm", "run": run}
