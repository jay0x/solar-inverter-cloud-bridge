"""Full control of implemented writable parameters; maintenance remains opt-in."""

MODES = ("full",)


def normalize_mode(value: str) -> str:
    # Compatibility for old internal callers, never a selectable restriction.
    if value not in (*MODES, "monitoring", "control", "advanced"):
        raise ValueError("unknown_control_mode")
    return "full"


def clock_write_allowed(enabled: bool) -> bool:
    return bool(enabled)


MAX_CLOCK_CORRECTION_SECONDS = 300


def clock_drift_seconds(observed: str, target: str) -> float:
    from datetime import datetime
    return abs((datetime.fromisoformat(target) - datetime.fromisoformat(observed)).total_seconds())
