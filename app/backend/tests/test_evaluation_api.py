from database import RecoveryCase, RecoveryStatus


def add_case(db, *, amount=10000, score=0.8):
    case = RecoveryCase(
        payment_id="pay_evaluation_api", amount=amount,
        status=RecoveryStatus.DIAGNOSED, diagnosis="incorrect pin",
        recommended_action="IMMEDIATE_RETRY", recoverability_score=score,
    )
    db.add(case)
    db.commit()
    return case


def test_evaluation_interventions_and_policy_config_endpoints(client, db):
    case = add_case(db)
    response = client.post(f"/cases/{case.id}/evaluate")
    assert response.status_code == 200
    body = response.json()
    assert body["case_status"] == "ACTION_SCHEDULED"
    assert body["policy"]["allowed"] is True
    assert body["decision"]["selected_action"] == "IMMEDIATE_RETRY"
    assert body["intervention"]["executed_at"] is None

    interventions = client.get(f"/cases/{case.id}/interventions")
    assert interventions.status_code == 200
    assert len(interventions.json()) == 1
    config = client.get("/policies/config")
    assert config.status_code == 200
    assert config.json() == {
        "max_interventions_per_case": 3,
        "minimum_automatic_score": 0.4,
        "high_value_review_threshold": 1000000,
        "currency_unit": "paise",
        "decision_version": "bounded-rules-v1",
        "policy_version": "recovery-policy-v1",
    }


def test_denial_is_http_200_and_missing_cases_are_404(client, db):
    case = add_case(db, amount=1_000_000)
    denied = client.post(f"/cases/{case.id}/evaluate")
    assert denied.status_code == 200
    assert denied.json()["policy"]["allowed"] is False
    assert client.post("/cases/missing/evaluate").status_code == 404
    assert client.get("/cases/missing/interventions").status_code == 404
