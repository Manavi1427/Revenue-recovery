from sqlalchemy import select

from database import AuditLog, RecoveryStatus
from ml.predictor import ModelUnavailableError
from services.case_service import process_failed_payment
from services.scoring_service import score_recovery_case


def payment(reason="incorrect_pin"):
    return {"id": f"pay_{reason}", "order_id": f"order_{reason}", "amount": 10000, "currency": "INR", "method": "upi", "error_reason": reason}


def test_scoring_persists_audits_and_does_not_change_status(db, monkeypatch):
    def unavailable(_row):
        raise ModelUnavailableError("missing")

    monkeypatch.setattr("services.scoring_service.predict_probability", unavailable)
    case = process_failed_payment(db, "evt_score", "payment.failed", payment(), {})
    original_status = case.status
    result = score_recovery_case(db, case)
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "RECOVERY_SCORED")).all()
    assert case.recoverability_score == result.final_score
    assert result.source == "RULES_FALLBACK"
    assert case.status == original_status == RecoveryStatus.DIAGNOSED
    assert len(logs) == 1  # Identical rescore does not create duplicate noise.


def test_human_review_status_is_preserved(db, monkeypatch):
    monkeypatch.setattr("services.scoring_service.predict_probability", lambda row: (0.4, "test-v1"))
    case = process_failed_payment(db, "evt_review", "payment.failed", payment("mystery"), {})
    assert case.status == RecoveryStatus.HUMAN_REVIEW
    assert case.recoverability_score == 0.4


def test_scoring_api_and_missing_case(client, db, monkeypatch):
    monkeypatch.setattr("services.scoring_service.predict_probability", lambda row: (0.72, "test-v1"))
    case = process_failed_payment(db, "evt_api_score", "payment.failed", payment(), {})
    response = client.post(f"/cases/{case.id}/score")
    assert response.status_code == 200
    assert response.json()["source"] == "ML"
    assert response.json()["final_score"] == 0.72
    assert client.post("/cases/not-found/score").status_code == 404


def test_model_status_is_healthy_without_optional_artifact(client, monkeypatch, tmp_path):
    monkeypatch.setattr("routes.scoring.get_model_status", lambda: {"model_available": False, "fallback_available": True})
    response = client.get("/model/status")
    assert response.status_code == 200
    assert response.json() == {"model_available": False, "fallback_available": True}
