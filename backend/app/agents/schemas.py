"""Validated structured outputs for every agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["stated", "inferred", "unknown"]


class FieldProposal(BaseModel):
    value: str | None = Field(description="Proposed value, or null if unknown")
    status: Status
    evidence: list[str] = Field(default_factory=list, max_length=4, description="Verbatim quotes from the description")
    explanation: str = Field(max_length=400)


class ListFieldProposal(BaseModel):
    value: list[str] = Field(default_factory=list, max_length=10)
    status: Status
    evidence: list[str] = Field(default_factory=list, max_length=4)
    explanation: str = Field(max_length=400)


class ClassificationProposal(BaseModel):
    use_type: FieldProposal = Field(description="human | veterinary | unknown")
    species: ListFieldProposal
    therapeutic_area: FieldProposal
    indication: FieldProposal
    modality: FieldProposal
    molecule_category: FieldProposal = Field(description="small_molecule | biologic | other | unknown")
    target: FieldProposal
    mechanism: FieldProposal
    route: FieldProposal
    jurisdictions: ListFieldProposal
    suggested_stage_template: Literal["veterinary", "human"]
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)
    public_search_terms: list[str] = Field(default_factory=list, max_length=5)
    regulatory_caution: str = Field(max_length=600)


EventType = Literal[
    "trial_registration", "trial_status_change", "published_results", "regulatory_submission", "regulatory_decision",
    "licensing_deal", "partnership", "financing", "manufacturing", "company_announcement", "publication", "other",
]


class EventAssessment(BaseModel):
    item_id: str
    relevant: bool
    event_type: EventType
    observed: str = Field(max_length=600)
    interpretation: str | None = Field(default=None, max_length=600)
    possible_next_move: str | None = Field(default=None, max_length=400)
    suggested_action: str | None = Field(default=None, max_length=400)
    relevance: int = Field(ge=0, le=100)
    relevance_reason: str = Field(max_length=300)
    company: str | None = Field(default=None, max_length=120)
    product: str | None = Field(default=None, max_length=120)


class IntelligenceReport(BaseModel):
    assessments: list[EventAssessment] = Field(default_factory=list, max_length=12)
    injection_detected: bool = False
    coverage_note: str = Field(default="", max_length=500)


class BriefingPick(BaseModel):
    item_id: str
    section: Literal["lead_candidate", "animal_health", "regulatory", "pipeline"]
    summary: str = Field(max_length=500)
    why_it_matters: str = Field(max_length=400)
    significance: int = Field(ge=0, le=100)
    pipeline_relevance: int = Field(ge=0, le=100)


class BriefingDraft(BaseModel):
    picks: list[BriefingPick] = Field(default_factory=list, max_length=10)
    injection_detected: bool = False


Topic = Literal[
    "classification_pathway", "preclinical", "clinical_or_field_studies", "cmc_quality", "safety", "efficacy",
    "submission_procedure", "conditional_or_accelerated", "post_approval", "other",
]


class Passage(BaseModel):
    text: str = Field(max_length=800)
    section: str | None = Field(default=None, max_length=80)


class RegulatoryAssessment(BaseModel):
    doc_id: str
    relevance: int = Field(ge=0, le=100)
    applicability: str = Field(max_length=800)
    topics: list[Topic] = Field(default_factory=list, max_length=6)
    summary_en: str = Field(max_length=800)
    is_translation: bool = False
    passages: list[Passage] = Field(default_factory=list, max_length=3)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=5)
    affected_milestone_ids: list[int] = Field(default_factory=list, max_length=6)


class RegulatoryReport(BaseModel):
    assessments: list[RegulatoryAssessment] = Field(default_factory=list, max_length=10)
    injection_detected: bool = False


Criterion = Literal[
    "therapeutic_species_fit", "portfolio_relevance", "geographic_capability", "commercial_capability",
    "prior_licensing_activity", "stated_strategic_interest",
]


class CriterionEvidence(BaseModel):
    criterion: Criterion
    evidence_ids: list[str] = Field(default_factory=list, max_length=6)


class PartnerAssessment(BaseModel):
    company: str
    criteria: list[CriterionEvidence] = Field(default_factory=list, max_length=6)
    assessment: str = Field(max_length=700)
    gaps: list[str] = Field(default_factory=list, max_length=5)


class PartnerReport(BaseModel):
    partners: list[PartnerAssessment] = Field(default_factory=list, max_length=8)
    injection_detected: bool = False


class KeyFigure(BaseModel):
    label: str = Field(max_length=120)
    value: str = Field(max_length=80)
    tool: str = Field(max_length=60)


class SourceRef(BaseModel):
    title: str = Field(max_length=300)
    url: str = Field(max_length=1000)


class AssistantAnswer(BaseModel):
    answer: str = Field(max_length=3000)
    key_figures: list[KeyFigure] = Field(default_factory=list, max_length=12)
    sources: list[SourceRef] = Field(default_factory=list, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    gaps: list[str] = Field(default_factory=list, max_length=8)
    suggested_actions: list[str] = Field(default_factory=list, max_length=5)
