"""Per-request AI/decision model selection, validated against fixed allowlists."""

from contextvars import ContextVar
from dataclasses import dataclass

AI_MODELS = ("gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5.5", "deepseek-v4.1-flash")
DEFAULT_REASONING_EFFORT = "medium"
REASONING_EFFORTS = {
    "gpt-6-luna": ("none", "low", "medium", "high", "xhigh", "max"),
    "gpt-6.1-sol": ("low", "medium", "high", "xhigh", "max"),
    "claude-sonnet-5.5": ("low", "medium", "high", "xhigh", "max"),
    "deepseek-v4.1-flash": ("low", "medium", "high"),
}
DECISION_MODELS = ("Microsoft-Decision-1", "Jev")
AI_MODEL_HEADER = b"x-ai-model"
REASONING_EFFORT_HEADER = b"x-reasoning-effort"
DECISION_MODEL_HEADER = b"x-decision-model"
SELECTION_HEADERS = {AI_MODEL_HEADER, REASONING_EFFORT_HEADER, DECISION_MODEL_HEADER}


@dataclass(frozen=True)
class Selection:
    ai_model: str | None = None
    decision_model: str | None = None
    reasoning_effort: str | None = None


current_selection: ContextVar[Selection] = ContextVar("model_selection", default=Selection())


def parse_selection(headers) -> Selection:
    """Invalid models use server defaults; valid models default invalid effort to Medium."""
    found: dict[bytes, list[str]] = {}
    for name, value in headers:
        name = name.lower()
        if name in SELECTION_HEADERS:
            try:
                decoded = value.decode("ascii")
                if any(ord(char) < 32 or ord(char) > 126 for char in decoded):
                    decoded = ""
                found.setdefault(name, []).append(decoded.strip(" "))
            except UnicodeDecodeError:
                found.setdefault(name, []).append("")

    def pick(name, allowed):
        values = found.get(name, [])
        return values[0] if len(values) == 1 and values[0] in allowed else None

    model = pick(AI_MODEL_HEADER, AI_MODELS)
    effort = (
        pick(REASONING_EFFORT_HEADER, REASONING_EFFORTS[model]) or DEFAULT_REASONING_EFFORT
        if model else None
    )
    return Selection(model, pick(DECISION_MODEL_HEADER, DECISION_MODELS), effort)
