from dataclasses import dataclass
import os


class DemoBatchConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DemoBatchSettings:
    enabled: bool
    batch_size: int
    seed: int
    treatment_percent: int


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise DemoBatchConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise DemoBatchConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def get_demo_batch_settings() -> DemoBatchSettings:
    enabled_value = os.getenv("DEMO_BATCH_ENABLED", "true").strip().lower()
    if enabled_value not in {"true", "false", "1", "0", "yes", "no"}:
        raise DemoBatchConfigurationError("DEMO_BATCH_ENABLED must be a boolean")
    return DemoBatchSettings(
        enabled=enabled_value in {"true", "1", "yes"},
        batch_size=_integer("DEMO_BATCH_SIZE", 100, 1, 500),
        seed=_integer("DEMO_BATCH_SEED", 42, -2_147_483_648, 2_147_483_647),
        treatment_percent=_integer("DEMO_TREATMENT_PERCENT", 80, 0, 100),
    )
