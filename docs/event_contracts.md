# Payloads 

### Normalized payment event

{
  "event_id": "evt_demo_001",
  "event_type": "payment.failed",
  "payment_id": "pay_demo_001",
  "order_id": "order_demo_001",
  "amount": 249900,
  "currency": "INR",
  "method": "upi",
  "error_source": "customer",
  "error_step": "payment_authentication",
  "error_reason": "incorrect_pin",
  "occurred_at": "2026-08-24T12:00:00Z"
}

### Recovery decision 

{
  "case_id": "case_001",
  "diagnosis": "Customer entered an incorrect UPI PIN",
  "recoverability_score": 0.84,
  "recommended_action": "IMMEDIATE_RETRY",
  "policy_allowed": true,
  "reason": "High-intent customer-correctable failure"
}

### Case summary response 

{
  "id": "case_001",
  "amount": 249900,
  "status": "ACTION_SCHEDULED",
  "diagnosis": "Customer entered an incorrect UPI PIN",
  "score": 0.84,
  "next_action": "IMMEDIATE_RETRY"
}