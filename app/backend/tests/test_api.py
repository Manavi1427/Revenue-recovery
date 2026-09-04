import hashlib
import hmac
import json

from database import AuditLog, RecoveryCase, RecoveryStatus


def test_case_list_detail_and_timeline(client, db):
    case = RecoveryCase(payment_id="pay_api", amount=100, status=RecoveryStatus.DETECTED)
    db.add(case)
    db.flush()
    later = AuditLog(recovery_case_id=case.id, action="SECOND")
    first = AuditLog(recovery_case_id=case.id, action="FIRST")
    db.add_all([first, later])
    db.commit()

    assert client.get("/cases").status_code == 200
    assert client.get(f"/cases/{case.id}").json()["id"] == case.id
    timeline = client.get(f"/cases/{case.id}/timeline").json()
    assert [entry["action"] for entry in timeline] == ["FIRST", "SECOND"]
    assert client.get("/cases/missing").status_code == 404


def test_invalid_webhook_signature_is_rejected(client):
    assert client.post("/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "bad"}).status_code == 400


def test_webhook_duplicate_event(client, db):
    payload = {"event": "payment.failed", "payload": {"payment": {"entity": {
        "id": "pay_hook", "order_id": "order_hook", "amount": 500,
        "currency": "INR", "error_reason": "incorrect_pin",
    }}}}
    body = json.dumps(payload).encode()
    signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    headers = {"X-Razorpay-Signature": signature, "X-Razorpay-Event-Id": "evt_hook"}
    first = client.post("/webhooks/razorpay", content=body, headers=headers)
    second = client.post("/webhooks/razorpay", content=body, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["case_id"] == second.json()["case_id"]


def test_health_is_sanitized_with_rule_fallback(client, monkeypatch):
    monkeypatch.setattr("main.get_model_status", lambda: {"model_available": False})
    response = client.get("/health")
    payload = response.json()
    assert response.status_code == 200
    assert payload["model_status"] == "rules_fallback"
    assert not ({"database_url", "key", "secret"} & payload.keys())


def test_ready_sanitizes_database_failure(client, monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("private database detail")

    monkeypatch.setattr("main.engine", BrokenEngine())
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "service": "recoveriq-api", "database": "unavailable"}
