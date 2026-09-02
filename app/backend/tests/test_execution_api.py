from datetime import datetime, timezone

from database import Intervention, RecoveryCase, RecoveryStatus


def scheduled(db):
    case = RecoveryCase(payment_id="pay_exec_api", amount=12500, status=RecoveryStatus.ACTION_SCHEDULED, recoverability_score=0.8)
    db.add(case)
    db.flush()
    intervention = Intervention(
        recovery_case_id=case.id, action_type="CREATE_PAYMENT_LINK", channel="PENDING",
        scheduled_at=datetime.now(timezone.utc), action_payload={"status": "PENDING_EXECUTION"},
    )
    db.add(intervention)
    db.commit()
    return case, intervention


def test_execution_status_demo_and_idempotent_api(client, db, monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "mock")
    monkeypatch.setenv("BACKEND_PUBLIC_URL", "http://testserver")
    case, intervention = scheduled(db)
    first = client.post(f"/interventions/{intervention.id}/execute")
    repeated = client.post(f"/interventions/{intervention.id}/execute")
    assert first.status_code == repeated.status_code == 200
    assert first.json()["case_status"] == "CONTACTED"
    assert repeated.json()["idempotent_replay"] is True
    assert first.json()["payment_link"] == repeated.json()["payment_link"]
    demo = client.get(f"/demo/payment-links/{intervention.id}")
    assert demo.status_code == 200
    assert demo.json()["mock"] is True
    assert demo.json()["amount"] == 12500
    status = client.get("/integrations/razorpay/status")
    assert status.json() == {"mode": "mock", "configured": True, "payment_link_execution_available": True}


def test_execution_api_expected_errors_and_test_status(client, monkeypatch):
    assert client.post("/interventions/missing/execute").status_code == 404
    monkeypatch.setenv("RAZORPAY_MODE", "test")
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    status = client.get("/integrations/razorpay/status")
    assert status.status_code == 200
    assert status.json() == {"mode": "test", "configured": False, "payment_link_execution_available": False}
    assert client.get("/demo/payment-links/anything").status_code == 404
