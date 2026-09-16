"""Provider boundary for question interpretation, without retrieval or approval."""

from typing import Protocol


class QuestionPlanner(Protocol):
    def interpret(self, question: str) -> str:
        """Return an untrusted JSON object conforming to StructuredQuestion."""
        ...


class PlannerUnavailable(Exception):
    """An adapter could not return an interpretation; never expose its details."""
