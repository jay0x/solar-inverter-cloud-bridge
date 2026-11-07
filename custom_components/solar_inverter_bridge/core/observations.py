"""Observation age. Reconnect and UI reads must not refresh it."""

from datetime import datetime, timezone

TELEMETRY_TTL_SECONDS = 60


class Observation:
    def __init__(self, values, observed_monotonic, observed_utc=None):
        self.values = values
        self.observed_monotonic = observed_monotonic
        self.observed_utc = observed_utc or datetime.now(timezone.utc).isoformat()
        self.boot_id = None

    def age(self, now):
        return max(0, now - self.observed_monotonic)

    def available(self, now, ttl=TELEMETRY_TTL_SECONDS):
        return self.age(now) <= ttl
