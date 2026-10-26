"""Pydantic models validating API input. Money crosses the API as decimal strings."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .phases import PHASES

Currency = Literal["USD", "HKD", "CNY"]
Category = Literal[
    "Research", "Preclinical studies", "Manufacturing / CMC", "Analytical work", "Regulatory",
    "Clinical / field studies", "CRO services", "Personnel", "Facilities", "Overhead",
]

VET_STAGES = [p["label"] for p in PHASES]  # see app/phases.py
HUMAN_STAGES = [
    "Discovery", "Preclinical (IND-enabling)", "Phase I", "Phase II", "Phase III", "Marketing application (NDA/BLA/MAA)", "Approved", "Post-marketing",
]
JURISDICTIONS = ["US", "EU", "CN", "JP", "KR", "HK", "UK", "Other"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class KeyDate(Strict):
    label: str = Field(max_length=120)
    date: date


class ProgramIn(Strict):
    code: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._\-]+$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    therapeutic_area: str | None = Field(default=None, max_length=120)
    indication: str | None = Field(default=None, max_length=200)
    use_type: Literal["human", "veterinary", "unknown"] = "unknown"
    species: list[str] = Field(default_factory=list, max_length=10)
    target: str | None = Field(default=None, max_length=200)
    mechanism: str | None = Field(default=None, max_length=300)
    modality: str | None = Field(default=None, max_length=120)
    molecule_category: Literal["small_molecule", "biologic", "other", "unknown"] = "unknown"
    route: str | None = Field(default=None, max_length=120)
    stage_template: Literal["veterinary", "human"] = "veterinary"
    stage: str | None = Field(default=None, max_length=120)
    status: Literal["active", "on_hold", "discontinued", "completed"] = "active"
    owner: str | None = Field(default=None, max_length=120)
    priority: Literal["high", "medium", "low"] = "medium"
    jurisdictions: list[str] = Field(default_factory=list, max_length=10)
    key_dates: list[KeyDate] = Field(default_factory=list, max_length=30)
    risks: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=8000)
    public_keywords: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("species", "jurisdictions", "public_keywords")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return [x.strip()[:80] for x in v if x and x.strip()]


class ProgramPatch(Strict):
    code: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._\-]+$")
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    therapeutic_area: str | None = None
    indication: str | None = None
    use_type: Literal["human", "veterinary", "unknown"] | None = None
    species: list[str] | None = None
    target: str | None = None
    mechanism: str | None = None
    modality: str | None = None
    molecule_category: Literal["small_molecule", "biologic", "other", "unknown"] | None = None
    route: str | None = None
    stage_template: Literal["veterinary", "human"] | None = None
    stage: str | None = None
    status: Literal["active", "on_hold", "discontinued", "completed"] | None = None
    owner: str | None = None
    priority: Literal["high", "medium", "low"] | None = None
    jurisdictions: list[str] | None = None
    key_dates: list[KeyDate] | None = None
    risks: str | None = None
    notes: str | None = None
    public_keywords: list[str] | None = None


class MilestoneIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    stage: str | None = Field(default=None, max_length=120)
    planned_start: date | None = None
    planned_end: date | None = None
    actual_end: date | None = None
    status: Literal["planned", "in_progress", "done", "at_risk", "cancelled"] = "planned"
    owner: str | None = Field(default=None, max_length=120)
    is_decision_point: bool = False
    depends_on: list[int] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=4000)
    sort_order: int = 0
    set_baseline: bool = False


class MilestonePatch(Strict):
    name: str | None = None
    description: str | None = None
    stage: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    actual_end: date | None = None
    status: Literal["planned", "in_progress", "done", "at_risk", "cancelled"] | None = None
    owner: str | None = None
    is_decision_point: bool | None = None
    depends_on: list[int] | None = None
    notes: str | None = None
    sort_order: int | None = None
    set_baseline: bool = False


class MoneyIn(Strict):
    amount: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    currency: Currency


class BudgetLineIn(Strict):
    program_id: int | None = None
    milestone_id: int | None = None
    category: Category
    description: str | None = Field(default=None, max_length=500)
    currency: Currency
    planned: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    contingency_pct: Decimal = Field(default=Decimal(0), ge=0, le=100, decimal_places=2)
    owner: str | None = Field(default=None, max_length=120)
    estimate_source: str | None = Field(default=None, max_length=500)
    assumptions: str | None = Field(default=None, max_length=2000)
    schedule: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("schedule")
    @classmethod
    def _months(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        import re

        for k, amt in v.items():
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", k):
                raise ValueError(f"schedule month {k!r} must be YYYY-MM")
            if amt < 0:
                raise ValueError("schedule amounts must be non-negative")
        return v


class BudgetApprove(Strict):
    approved: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)


class AccountIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    legal_entity: str = Field(min_length=1, max_length=160)
    entity_base_currency: Currency = "HKD"
    currency: Currency


class BalanceIn(Strict):
    account_id: int
    as_of_date: date
    balance: Decimal = Field(max_digits=16, decimal_places=2)
    source: str | None = Field(default=None, max_length=300)


class FxRateIn(Strict):
    base: Literal["USD", "HKD", "CNY", "EUR"]
    quote: Literal["USD", "HKD", "CNY", "EUR"]
    rate: Decimal = Field(gt=0, max_digits=20, decimal_places=10)
    rate_date: date
    source: str = Field(min_length=1, max_length=200)


class CommitmentIn(Strict):
    program_id: int | None = None
    milestone_id: int | None = None
    category: Category | None = None
    counterparty: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    currency: Currency
    amount: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    expected_payment_date: date | None = None


class PlannedFlowIn(Strict):
    label: str = Field(min_length=1, max_length=200)
    flow_date: date
    amount: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    currency: Currency
    direction: Literal["inflow", "outflow"]
    kind: Literal["operating", "financing"] = "operating"
    certainty: Literal["confirmed", "hypothetical"] = "hypothetical"


class AllocationRuleIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    category: Category | None = None
    shares_pct: dict[int, Decimal]
    note: str | None = Field(default=None, max_length=500)


class TxnPatch(Strict):
    category: Category | None = None
    program_id: int | None = None
    milestone_id: int | None = None
    allocation: Literal["direct", "shared", "unallocated"] | None = None
    kind: Literal["operating", "refund", "financing", "transfer"] | None = None
    commitment_id: int | None = None
    account_id: int | None = None


class ScenarioIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["base", "accelerated", "conservative", "custom"] = "custom"
    description: str | None = Field(default=None, max_length=1000)
    assumptions: dict = Field(default_factory=dict)


class SettingsIn(Strict):
    reporting_currency: Currency | None = None
    min_reserve: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    burn_period_months: int | None = Field(default=None, ge=1, le=24)
    horizon_months: int | None = Field(default=None, ge=3, le=60)
    timezone: str | None = Field(default=None, max_length=64)
    company_name: str | None = Field(default=None, max_length=160)
    as_of_override: date | None = None
    clear_as_of_override: bool = False


class ActionIn(Strict):
    title: str = Field(min_length=1, max_length=300)
    detail: str | None = Field(default=None, max_length=2000)
    program_id: int | None = None
    owner: str | None = Field(default=None, max_length=120)
    priority: Literal["high", "medium", "low"] = "medium"
    due_date: date | None = None
    status: Literal["proposed", "open", "done", "dismissed"] = "open"


class ActionPatch(Strict):
    owner: str | None = None
    priority: Literal["high", "medium", "low"] | None = None
    due_date: date | None = None
    status: Literal["proposed", "open", "done", "dismissed"] | None = None
    title: str | None = None
    detail: str | None = None


class CompetitorIn(Strict):
    program_id: int | None = None
    company: str = Field(min_length=1, max_length=200)
    product: str | None = Field(default=None, max_length=200)
    species: list[str] = Field(default_factory=list, max_length=10)
    indication: str | None = Field(default=None, max_length=200)
    mechanism: str | None = Field(default=None, max_length=300)
    modality: str | None = Field(default=None, max_length=120)
    geography: str | None = Field(default=None, max_length=200)
    stage: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)
    status: Literal["tracked", "suggested", "dismissed"] = "tracked"


class ClassifyIn(Strict):
    description: str = Field(min_length=10, max_length=3000)
    program_id: int | None = None
    language: Literal["en", "zh"] = "en"


class ConfirmProfileIn(Strict):
    proposal_id: int
    profile: ProgramPatch


class AskIn(Strict):
    question: str = Field(min_length=3, max_length=1500)
    program_id: int | None = None
    scenario_id: int | None = None
    language: Literal["en", "zh"] = "en"


class CompanyIn(Strict):
    mission: str = Field(default="", max_length=600)
    values: list[str] = Field(default_factory=list, max_length=8)


class UrlResearchIn(Strict):
    url: str = Field(min_length=8, max_length=1000)
    program_id: int
