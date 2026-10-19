"""Per-request AI/decision model selection, validated against fixed allowlists."""

from contextvars import ContextVar
from dataclasses import dataclass

AI_MODELS = ("gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5.5")
DECISION_MODELS = ("Microsoft-Decision-1", "Jev")
AI_MODEL_HEADER = b"x-ai-model"
DECISION_MODEL_HEADER = b"x-decision-model"
SELECTION_HEADERS = {AI_MODEL_HEADER, DECISION_MODEL_HEADER}


@dataclass(frozen=True)
class Selection:
    ai_model: str | None = None
    decision_model: str | None = None


current_selection: ContextVar[Selection] = ContextVar("model_selection", default=Selection())


def parse_selection(headers) -> Selection:
    """Unknown, duplicate or malformed values are ignored so the server default applies."""
    found: dict[bytes, list[str]] = {}
    for name, value in headers:
        name = name.lower()
        if name in SELECTION_HEADERS:
            try:
                found.setdefault(name, []).append(value.decode("ascii").strip())
            except UnicodeDecodeError:
                found.setdefault(name, []).append("")

    def pick(name, allowed):
        values = found.get(name, [])
        return values[0] if len(values) == 1 and values[0] in allowed else None

    return Selection(pick(AI_MODEL_HEADER, AI_MODELS), pick(DECISION_MODEL_HEADER, DECISION_MODELS))
