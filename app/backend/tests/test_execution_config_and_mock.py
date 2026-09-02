import pytest

from execution_config import ExecutionConfigurationError, get_execution_settings
from integrations.mock_payment_link import MockPaymentLinkProvider
from integrations.payment_link_provider import PaymentLinkRequest


def test_mock_mode_needs_no_credentials_and_is_stable(monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "mock")
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    settings = get_execution_settings(require_test_credentials=True)
    provider = MockPaymentLinkProvider(settings.backend_public_url)
    request = PaymentLinkRequest("case-1", "intervention-1", 12500, "INR")
    first = provider.create_payment_link(request)
    repeated = provider.create_payment_link(request)
    assert (first.payment_link_id, first.short_url, first.reference_id) == (
        repeated.payment_link_id, repeated.short_url, repeated.reference_id,
    )
    assert first.payment_link_id == "plink_mock_intervention-1"
    other = provider.create_payment_link(PaymentLinkRequest("case-1", "intervention-2", 12500, "INR"))
    assert other.payment_link_id != "plink_mock_intervention-1"


def test_test_mode_requires_credentials_and_live_mode_is_impossible(monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "test")
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
    with pytest.raises(ExecutionConfigurationError):
        get_execution_settings(require_test_credentials=True)
    monkeypatch.setenv("RAZORPAY_MODE", "live")
    with pytest.raises(ExecutionConfigurationError):
        get_execution_settings()


def test_obvious_live_key_is_rejected_in_test_mode(monkeypatch):
    monkeypatch.setenv("RAZORPAY_MODE", "test")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_not_allowed")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    with pytest.raises(ExecutionConfigurationError):
        get_execution_settings(require_test_credentials=True)
