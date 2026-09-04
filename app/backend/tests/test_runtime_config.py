import pytest

from runtime_config import RuntimeConfigurationError, frontend_origins, normalize_database_url, validate_production_config


def test_database_url_normalization():
    assert normalize_database_url("postgres://host/db") == "postgresql://host/db"
    assert normalize_database_url("sqlite:///demo.db") == "sqlite:///demo.db"


def test_cors_allowlist_is_trimmed_and_rejects_wildcard(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGINS", "http://localhost:3000, https://recoveriq.example/")
    assert frontend_origins() == ["http://localhost:3000", "https://recoveriq.example"]
    monkeypatch.setenv("FRONTEND_ORIGINS", "*")
    with pytest.raises(RuntimeConfigurationError):
        frontend_origins()


def test_production_rejects_live_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://private")
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://recoveriq.example")
    monkeypatch.setenv("RAZORPAY_MODE", "live")
    with pytest.raises(RuntimeConfigurationError, match="mock or test"):
        validate_production_config()
