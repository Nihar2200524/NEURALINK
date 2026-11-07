"""Allowlisted, content-free telemetry."""
import json
import logging
from prometheus_client import Counter, Gauge, Histogram

SESSIONS = Gauge("agentra_active_sessions", "Registered sessions")
OUTCOMES = Counter("agentra_action_outcomes_total", "Action receipts", ["kind", "status"])
LATENCY = Histogram("agentra_action_seconds", "Dispatch duration")
RECOVERIES = Counter("agentra_recoveries_total", "Worker recoveries")
LIMITS = Counter("agentra_resource_stops_total", "Worker resource stops")
LOG = logging.getLogger("agentra.audit")


def audit(event: str, session_id: str, status: str) -> None:
    # Never include URLs, page data, tokens, selectors, or typed values.
    LOG.warning(json.dumps({"event": event, "session_id": session_id, "status": status}))
