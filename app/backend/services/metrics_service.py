from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import AuditLog, ExperimentGroup, RecoveryCase, RecoveryStatus


TERMINAL = (
    RecoveryStatus.RECOVERED,
    RecoveryStatus.EXHAUSTED,
    RecoveryStatus.SUPPRESSED,
)


def _rate(recovered: int, exposure: int) -> float | None:
    return round(recovered / exposure, 6) if exposure else None


def calculate_overview_metrics(
    db: Session, batch_id: str | None = None
) -> dict[str, object]:
    """Calculate persisted revenue metrics, optionally scoped to one demo batch.

    ``interventions_attempted`` counts distinct execution-start audit events.
    ``suppressed_interventions`` counts treatment policy evaluations that denied
    scheduling, including deterministic human-review and exhaustion outcomes.
    Existing ``money_at_risk`` semantics remain current outstanding exposure;
    ``initial_money_at_risk`` is the original denominator used for rates.
    """

    statement = select(RecoveryCase)
    if batch_id is not None:
        statement = statement.where(RecoveryCase.batch_id == batch_id)
    cases = list(db.scalars(statement).all())
    case_ids = [case.id for case in cases]
    total = len(cases)
    recovered_cases = [case for case in cases if case.status == RecoveryStatus.RECOVERED]
    treatment = [case for case in cases if case.experiment_group == ExperimentGroup.TREATMENT.value]
    holdout = [case for case in cases if case.experiment_group == ExperimentGroup.HOLDOUT.value]
    ineligible = [case for case in cases if case.experiment_group == ExperimentGroup.INELIGIBLE.value]
    initial = sum(case.amount for case in cases)
    recovered_amount = sum(case.amount for case in recovered_cases)
    outstanding = initial - recovered_amount
    treatment_exposure = sum(case.amount for case in treatment)
    holdout_exposure = sum(case.amount for case in holdout)
    treatment_recovered = [case for case in treatment if case.status == RecoveryStatus.RECOVERED]
    holdout_recovered = [case for case in holdout if case.status == RecoveryStatus.RECOVERED]
    treatment_amount = sum(case.amount for case in treatment_recovered)
    holdout_amount = sum(case.amount for case in holdout_recovered)
    treatment_rate = _rate(treatment_amount, treatment_exposure)
    holdout_rate = _rate(holdout_amount, holdout_exposure)
    lift = (
        round(treatment_rate - holdout_rate, 6)
        if treatment_rate is not None and holdout_rate is not None
        else None
    )
    durations = [
        (case.closed_at - case.opened_at).total_seconds()
        for case in recovered_cases
        if case.closed_at is not None and case.closed_at >= case.opened_at
    ]

    attempted = 0
    suppressed = 0
    if case_ids:
        audit_rows = db.scalars(
            select(AuditLog).where(AuditLog.recovery_case_id.in_(case_ids))
        ).all()
        attempted = len({
            str(log.decision_data.get("intervention_id"))
            for log in audit_rows
            if log.action == "INTERVENTION_EXECUTION_STARTED"
            and log.decision_data.get("intervention_id")
        })
        treatment_ids = {case.id for case in treatment}
        suppressed = sum(
            1 for log in audit_rows
            if log.recovery_case_id in treatment_ids
            and log.action == "POLICY_EVALUATED"
            and log.decision_data.get("allowed") is False
        )

    return {
        "batch_id": batch_id,
        "total_cases": total,
        "active_cases": sum(case.status not in TERMINAL for case in cases),
        "eligible_cases": len(treatment) + len(holdout),
        "treatment_cases": len(treatment),
        "holdout_cases": len(holdout),
        "ineligible_cases": len(ineligible),
        "money_at_risk": outstanding,
        "initial_money_at_risk": initial,
        "recovered_amount": recovered_amount,
        "outstanding_amount": outstanding,
        "gross_recovery_rate": _rate(recovered_amount, initial),
        "treatment_recovery_rate": treatment_rate,
        "holdout_recovery_rate": holdout_rate,
        "incremental_lift": lift,
        "average_recovery_time_seconds": (
            round(sum(durations) / len(durations), 3) if durations else None
        ),
        "interventions_attempted": attempted,
        "suppressed_interventions": suppressed,
        "recovered_cases": len(recovered_cases),
        "treatment_recovered_cases": len(treatment_recovered),
        "holdout_recovered_cases": len(holdout_recovered),
    }
