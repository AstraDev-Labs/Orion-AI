"""External-framework subprocess backends (Hermes Agent, OpenClaw)."""

from orion.evals.backends.external.hermes_agent import HermesBackend
from orion.evals.backends.external.openclaw import OpenClawBackend

__all__ = ["HermesBackend", "OpenClawBackend"]
