from integrations.payment_link_provider import PaymentLinkProviderError, PaymentLinkRequest
from integrations.razorpay_payment_link import RazorpayTestPaymentLinkProvider


class FakePaymentLinks:
    def __init__(self):
        self.payload = None

    def create(self, payload):
        self.payload = payload
        return {"id": "plink_test_123", "short_url": "https://rzp.io/i/test", "status": "created", "created_at": 1700000000}


class FakeClient:
    def __init__(self):
        self.payment_link = FakePaymentLinks()


def test_test_provider_builds_safe_payload_and_sanitized_result():
    client = FakeClient()
    provider = RazorpayTestPaymentLinkProvider("rzp_test_key", "secret", client=client)
    result = provider.create_payment_link(PaymentLinkRequest("case-1", "int-1", 12500, "INR"))
    assert client.payment_link.payload == {
        "amount": 12500,
        "currency": "INR",
        "reference_id": "recoveriq_case_case-1_intervention_int-1",
        "description": "RecoverIQ recovery for case case-1",
        "accept_partial": False,
        "reminder_enable": False,
        "notify": {"sms": False, "email": False},
    }
    assert result.provider == "razorpay"
    assert result.mode == "test"
    assert result.payment_link_id == "plink_test_123"
    assert "secret" not in str(result)


def test_test_provider_rejects_live_key_and_malformed_response():
    try:
        RazorpayTestPaymentLinkProvider("rzp_live_key", "secret", client=FakeClient())
        assert False, "live key should have failed"
    except PaymentLinkProviderError:
        pass

    client = FakeClient()
    client.payment_link.create = lambda payload: {"id": "missing-url"}
    provider = RazorpayTestPaymentLinkProvider("rzp_test_key", "secret", client=client)
    try:
        provider.create_payment_link(PaymentLinkRequest("case", "int", 100, "INR"))
        assert False, "malformed response should have failed"
    except PaymentLinkProviderError as exc:
        assert "missing-url" not in str(exc)
