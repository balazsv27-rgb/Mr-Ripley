"""
input_bounding.py — Deterministic token budget truncation.

Enforces a hard prompt budget by truncating inputs in priority order.
Lowest-priority inputs are truncated first.

Priority (highest to lowest):
1. Skill instructions — never truncated
2. Agent instructions
3. Artifact payloads
4. Document content
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Rough token estimate: 1 token ≈ 4 chars for English text.
_CHARS_PER_TOKEN = 4


@dataclass
class BoundedInput:
    """A single input with priority and truncation state."""

    name: str
    content: str
    priority: int  # lower = higher priority (1=skill, 4=document)
    truncated: bool = False
    original_chars: int = 0


@dataclass
class BoundingResult:
    """Result of input bounding."""

    inputs: list[BoundedInput]
    total_tokens: int
    budget: int
    truncated: bool = False
    truncation_events: list[dict[str, str | int]] = field(default_factory=list)


def estimate_tokens(text: str) -> int:
    """Estimate token count from character count."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def bound_inputs(
    inputs: list[BoundedInput],
    budget: int,
) -> BoundingResult:
    """Apply deterministic token budget truncation.

    Truncates from lowest priority first (highest priority number).
    Priority 1 inputs (skills) are never truncated.

    Returns a ``BoundingResult`` with truncated inputs and truncation events.
    """
    total = sum(estimate_tokens(inp.content) for inp in inputs)

    if total <= budget:
        return BoundingResult(
            inputs=inputs,
            total_tokens=total,
            budget=budget,
            truncated=False,
        )

    # Sort by priority descending (truncate lowest priority first)
    sorted_inputs = sorted(inputs, key=lambda x: x.priority, reverse=True)
    events: list[dict[str, str | int]] = []
    remaining = total

    for inp in sorted_inputs:
        if remaining <= budget:
            break

        # Never truncate priority 1 (skills)
        if inp.priority <= 1:
            continue

        inp_tokens = estimate_tokens(inp.content)
        excess = remaining - budget

        if excess >= inp_tokens:
            # Remove entirely
            inp.original_chars = len(inp.content)
            inp.content = ""
            inp.truncated = True
            remaining -= inp_tokens
            events.append({
                "name": inp.name,
                "priority": inp.priority,
                "removed_tokens": inp_tokens,
                "action": "removed",
            })
        else:
            # Partial truncation: keep enough chars to fit budget
            keep_tokens = inp_tokens - excess
            keep_chars = keep_tokens * _CHARS_PER_TOKEN
            inp.original_chars = len(inp.content)
            inp.content = inp.content[:keep_chars] + "\n[... truncated ...]"
            inp.truncated = True
            remaining -= excess
            events.append({
                "name": inp.name,
                "priority": inp.priority,
                "removed_tokens": excess,
                "action": "truncated",
            })

    return BoundingResult(
        inputs=sorted(inputs, key=lambda x: x.priority),  # restore priority order
        total_tokens=remaining,
        budget=budget,
        truncated=True,
        truncation_events=events,
    )
