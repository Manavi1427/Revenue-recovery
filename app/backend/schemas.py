
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from database import ExperimentGroup, RecoveryStatus
from services.recovery_actions import RecoveryAction


class PaymentEventBase(BaseModel):
    """Normalized payment-event data shared by create and read schemas."""

    event_id: str
    event_type: str
    payment_id: str | None = None
    order_id: str | None = None
    amount: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    payment_method: str | None = None
    error_code: str | None = None
    error_source: str | None = None
    error_step: str | None = None
    error_reason: str | None = None
    error_description: str | None = None
    normalized_payload: dict[str, Any] = Field(default_factory=dict)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class PaymentEventCreate(PaymentEventBase):
    """Data accepted when storing a normalized webhook event."""


class PaymentEventRead(PaymentEventBase):
    """Payment-event data returned from the database."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    recovery_case_id: str | None = None
    received_at: datetime


class RecoveryCaseBase(BaseModel):
    """Editable business data shared by recovery-case schemas."""

    payment_id: str | None = None
    order_id: str | None = None
    payment_method: str | None = None
    amount: int = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    diagnosis: str | None = None
    recoverability_score: float | None = Field(default=None, ge=0, le=1)
    recommended_action: str | None = None
    batch_id: str | None = None
    experiment_group: ExperimentGroup | None = None


class RecoveryCaseCreate(RecoveryCaseBase):
    """Data accepted when opening a recovery case."""

    status: RecoveryStatus = RecoveryStatus.DETECTED


class RecoveryCaseUpdate(BaseModel):
    """Fields that may be changed on an existing recovery case."""

    diagnosis: str | None = None
    recoverability_score: float | None = Field(default=None, ge=0, le=1)
    recommended_action: str | None = None
    status: RecoveryStatus | None = None
    closed_at: datetime | None = None


class RecoveryCaseRead(RecoveryCaseBase):
    """Flat recovery-case data returned from the database."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: RecoveryStatus
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class InterventionBase(BaseModel):
    """Recovery-action data shared by create and read schemas."""

    action_type: str
    channel: str | None = None
    action_payload: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] | None = None
    scheduled_at: datetime | None = None
    executed_at: datetime | None = None
    cancelled_at: datetime | None = None
    successful: bool | None = None
    cost: int | None = Field(default=None, ge=0)


class InterventionCreate(InterventionBase):
    """Data accepted when creating an intervention."""

    recovery_case_id: str


class InterventionUpdate(BaseModel):
    """Fields that may be changed on an existing intervention."""

    scheduled_at: datetime | None = None
    executed_at: datetime | None = None
    cancelled_at: datetime | None = None
    successful: bool | None = None
    result_payload: dict[str, Any] | None = None


class InterventionRead(InterventionBase):
    """Intervention data returned from the database."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    recovery_case_id: str
    created_at: datetime


class AuditLogCreate(BaseModel):
    """Data accepted when appending an audit-log entry."""

    recovery_case_id: str
    payment_event_id: str | None = None
    action: str
    actor: str = "SYSTEM"
    message: str | None = None
    previous_status: RecoveryStatus | None = None
    new_status: RecoveryStatus | None = None
    decision_data: dict[str, Any] = Field(default_factory=dict)
    policy_checks: dict[str, Any] = Field(default_factory=dict)


class AuditLogRead(AuditLogCreate):
    """Audit-log data returned from the database."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class ScoringResponse(BaseModel):
    """Safe API representation of one recovery scoring decision."""

    case_id: str
    final_score: float = Field(ge=0, le=1)
    source: str
    rule_score: float = Field(ge=0, le=1)
    ml_score: float | None = Field(default=None, ge=0, le=1)
    model_version: str | None = None
    explanation: list[str]


class DecisionResponse(BaseModel):
    selected_action: RecoveryAction
    recoverability_score: float = Field(ge=0, le=1)
    expected_recovery_value: int
    operational_cost: int
    fatigue_penalty: int
    risk_penalty: int
    utility: int
    explanation: list[str]
    candidate_actions: list[RecoveryAction]
    decision_version: str


class PolicyResponse(BaseModel):
    allowed: bool
    checks: dict[str, bool]
    denial_reason: str | None
    resulting_status: RecoveryStatus
    requires_human_review: bool
    policy_version: str


class InterventionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_type: RecoveryAction
    channel: str | None
    action_payload: dict[str, Any]
    result_payload: dict[str, Any] | None
    scheduled_at: datetime | None
    executed_at: datetime | None
    cancelled_at: datetime | None
    successful: bool | None
    cost: int | None
    created_at: datetime


class EvaluationResponse(BaseModel):
    case_id: str
    case_status: RecoveryStatus
    recoverability_score: float = Field(ge=0, le=1)
    score_source: str
    decision: DecisionResponse
    policy: PolicyResponse
    intervention: InterventionSummary | None


class PaymentLinkResponse(BaseModel):
    payment_link_id: str
    reference_id: str
    short_url: str
    status: str
    created_at: datetime


class RecoveryMessageResponse(BaseModel):
    title: str
    body: str
    cta_label: str
    payment_url: str
    language: str
    source: str


class InterventionExecutionResponse(BaseModel):
    case_id: str
    case_status: RecoveryStatus
    intervention_id: str
    action_type: RecoveryAction
    provider: str
    mode: str
    payment_link: PaymentLinkResponse
    message: RecoveryMessageResponse
    idempotent_replay: bool


class RazorpayIntegrationStatusResponse(BaseModel):
    mode: str
    configured: bool
    payment_link_execution_available: bool


class DemoBatchRequest(BaseModel):
    seed: int = 42
    batch_size: int = Field(default=100, ge=1, le=500)
    treatment_percent: int = Field(default=80, ge=0, le=100)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)


class OverviewMetricsResponse(BaseModel):
    """Rates are decimals: 0.42 means 42%, and lift is percentage-point lift."""

    batch_id: str | None = None
    total_cases: int
    active_cases: int
    eligible_cases: int
    treatment_cases: int
    holdout_cases: int
    ineligible_cases: int
    money_at_risk: int
    initial_money_at_risk: int
    recovered_amount: int
    outstanding_amount: int
    gross_recovery_rate: float | None
    treatment_recovery_rate: float | None
    holdout_recovery_rate: float | None
    incremental_lift: float | None
    average_recovery_time_seconds: float | None
    interventions_attempted: int
    suppressed_interventions: int
    recovered_cases: int
    treatment_recovered_cases: int
    holdout_recovered_cases: int


class DemoBatchResponse(BaseModel):
    batch_id: str
    seed: int
    requested_cases: int
    created_cases: int
    treatment_cases: int
    holdout_cases: int
    ineligible_cases: int
    recovered_cases: int
    interventions_attempted: int
    suppressed_interventions: int
    status: str
    simulated: bool = True
    metrics: OverviewMetricsResponse
    idempotent_replay: bool


class PaymentMethodHealth(BaseModel):
    payment_method: str
    status: str
    total_attempts: int
    failed_attempts: int
    observed_failure_rate: float | None
    baseline_failure_rate: float | None
    threshold: float
    degradation_limit: float | None
    recommended_action: str | None
    reminders_suppressed: bool
    reason: str


class PaymentHealthResponse(BaseModel):
    batch_id: str | None
    window_start: datetime | None
    window_end: datetime | None
    overall_status: str
    degraded_methods: list[str]
    methods: list[PaymentMethodHealth]
    generated_at: datetime
    simulated: bool
