from services.scoring_service import calculate_rule_score


def score(reason=None, attempts=1, method="card", source="bank"):
    return calculate_rule_score(
        amount=10000,
        payment_method=method,
        error_source=source,
        error_step="payment_authentication",
        error_reason=reason,
        previous_attempts=attempts,
    ).score


def test_rule_score_is_clamped_to_probability_range():
    assert 0 <= score("incorrect_pin", method="upi", source="customer") <= 1
    assert 0 <= score("unknown", attempts=100) <= 1


def test_incorrect_pin_scores_higher_than_expired_card():
    assert score("incorrect_pin") > score("expired_card")


def test_repeated_failures_reduce_score():
    assert score("incorrect_pin", attempts=3) < score("incorrect_pin", attempts=1)


def test_missing_error_fields_do_not_crash_and_count_as_unknown():
    missing = calculate_rule_score(
        amount=0,
        payment_method=None,
        error_source=None,
        error_step=None,
        error_reason=None,
        previous_attempts=1,
    )
    assert missing.score == 0.30


def test_unknown_failure_scores_lower_and_rules_are_deterministic():
    first = score("unknown")
    assert first < score("incorrect_pin")
    assert first == score("unknown")
