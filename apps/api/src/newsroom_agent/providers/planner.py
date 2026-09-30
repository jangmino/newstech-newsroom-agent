"""Provider boundary for question interpretation, without retrieval or approval."""

from typing import Protocol


class QuestionPlanner(Protocol):
    def interpret(self, question: str) -> str:
        """Return an untrusted JSON object conforming to StructuredQuestion."""
        ...


class PlannerUnavailable(Exception):
    """An adapter could not return an interpretation; never expose its details."""


class PlannerDisabled(PlannerUnavailable):
    """Live planning has not been explicitly enabled by the server operator."""


class PlannerConfigurationError(PlannerUnavailable):
    """Required backend configuration is absent or unsupported."""


class PlannerRateLimited(PlannerUnavailable):
    """Local call budget or provider quota prevented this request."""


class PlannerTimedOut(PlannerUnavailable):
    """The provider did not respond within the HTTP timeout."""


class PlannerBillingError(PlannerUnavailable):
    """Prepaid credits or billing require operator action."""


class PlannerAuthenticationError(PlannerUnavailable):
    """Credential or provider permission requires operator action."""
