from enum import Enum


class RecoveryAction(str, Enum):
    """The complete allowlist of actions the decision engine may select."""

    IMMEDIATE_RETRY = "IMMEDIATE_RETRY"
    RETRY_LATER = "RETRY_LATER"
    CREATE_PAYMENT_LINK = "CREATE_PAYMENT_LINK"
    SUGGEST_ALTERNATIVE_METHOD = "SUGGEST_ALTERNATIVE_METHOD"
    REQUEST_NEW_METHOD = "REQUEST_NEW_METHOD"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    STOP_CASE = "STOP_CASE"


DECISION_VERSION = "bounded-rules-v1"
POLICY_VERSION = "recovery-policy-v1"

# Prototype assumptions in paise, not actual Razorpay or provider fees.
OPERATIONAL_COSTS = {
    RecoveryAction.IMMEDIATE_RETRY: 0,
    RecoveryAction.RETRY_LATER: 0,
    RecoveryAction.CREATE_PAYMENT_LINK: 100,
    RecoveryAction.SUGGEST_ALTERNATIVE_METHOD: 50,
    RecoveryAction.REQUEST_NEW_METHOD: 50,
    RecoveryAction.HUMAN_REVIEW: 5000,
    RecoveryAction.STOP_CASE: 0,
}
FATIGUE_PENALTY_PER_INTERVENTION = 100
RISK_PENALTY_PER_REPEAT_ATTEMPT = 100

MAX_INTERVENTIONS_PER_CASE = 3
MIN_AUTOMATIC_SCORE = 0.40
# 1,000,000 paise is INR 10,000; prototype cases at or above it need review.
HIGH_VALUE_REVIEW_THRESHOLD = 1_000_000
