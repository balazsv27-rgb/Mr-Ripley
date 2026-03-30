"""
layer2/constants.py
-------------------
Shared constants for the Mr. Ripley Gold-First Decision Engine.

This module defines the canonical ReasonCode enum used at the Layer-2 →
Layer-3 execution boundary. All reason codes that flow from Layer-3 into
a DecisionPacket must be drawn from this enum. Free-text reason values at
the execution boundary are prohibited.

Usage:
    from layer2.constants import ReasonCode

    # In a DecisionPacket or gate evaluation:
    reason = ReasonCode.NO_SIGNAL
    reason = ReasonCode.DATA_STALE
    reason_str = ReasonCode.NO_SIGNAL.value   # "NO_SIGNAL"

    # Validation helper:
    ReasonCode.validate("NO_SIGNAL")    # returns ReasonCode.NO_SIGNAL
    ReasonCode.validate("bad_value")    # raises ValueError

Architecture note:
    ReasonCode is defined here in Layer-2 so it can be imported by both
    Layer-2 (snapshot_publisher, quality gate) and Layer-3 (decision
    engine, DecisionPacket). It is intentionally minimal at bootstrap.
    New codes are added here as Layer-3 build progresses.

    No free text is permitted at the execution boundary. Any component
    that needs to express a reason must use a value from this enum.

Layer-3 bootstrap note:
    The initial build sequence requires only NO_SIGNAL / NO_TRADE as the
    default output codes. Additional codes are staged in groups below
    to communicate design intent without requiring immediate implementation.
"""

from __future__ import annotations

from enum import Enum
from typing import Union


# ---------------------------------------------------------------------------
# ReasonCode enum
# ---------------------------------------------------------------------------

class ReasonCode(str, Enum):
    """
    Enumerated reason codes for the Layer-2 → Layer-3 execution boundary.

    All DecisionPacket `reason_code` fields must use a value from this enum.
    Free text at the execution boundary is prohibited.

    Codes are organised into groups. Only the first two groups are required
    at Layer-3 bootstrap. Later groups are defined here for forward-compatible
    interface stability.

    Inheritance from `str` allows direct JSON serialisation:
        json.dumps({"reason_code": ReasonCode.NO_SIGNAL})
        → '{"reason_code": "NO_SIGNAL"}'
    """

    # ── Group 0: Layer-2 data-layer codes ────────────────────────────────
    # Used by snapshot_publisher and quality_gate to characterise the
    # data state of a published snapshot. These codes flow into Layer-3
    # via the guards.data_ok flag, not as primary DecisionPacket outputs.

    DATA_OK          = "DATA_OK"           # All Tier-1 series fresh; snapshot valid
    DATA_STALE       = "DATA_STALE"        # One or more Tier-1 series exceeded staleness threshold
    DATA_MISSING     = "DATA_MISSING"      # One or more required series absent from aligned payload
    DATA_FORCED      = "DATA_FORCED"       # Snapshot published with --force; gate FAIL bypassed

    # ── Group 1: Default / bootstrap codes ───────────────────────────────
    # Required at Layer-3 Phase 1 bootstrap. These are the only codes the
    # initial DecisionPacket skeleton needs to emit.

    NO_SIGNAL        = "NO_SIGNAL"         # No actionable signal computed; default safe output
    NO_TRADE         = "NO_TRADE"          # Trade not taken; default when guards are not satisfied

    # ── Group 2: Guard / veto codes ──────────────────────────────────────
    # Emitted when a hard veto condition blocks execution. These are the
    # codes Layer-3's Supervisor Engine produces when a guard fails.

    VETO_DATA        = "VETO_DATA"         # data_ok == False → hard NO TRADE
    VETO_IDEMPOTENT  = "VETO_IDEMPOTENT"   # idempotent_ok == False → duplicate guard triggered
    VETO_COOLDOWN    = "VETO_COOLDOWN"     # cooldown_ok == False → within cooldown window
    VETO_RISK        = "VETO_RISK"         # risk_ok == False → risk cap exceeded
    VETO_SUPERVISOR  = "VETO_SUPERVISOR"   # supervisor_veto == True → explicit supervisor block
    VETO_UNKNOWN_MODE = "VETO_UNKNOWN_MODE" # UnknownMode active → hard NO TRADE

    # ── Group 3: Signal / regime codes ───────────────────────────────────
    # Emitted by Layer-3 regime and signal logic. Not required at bootstrap;
    # defined here for forward-compatible interface stability.

    REGIME_NORMAL    = "REGIME_NORMAL"     # Normal macro regime; standard signal evaluation
    REGIME_STRESS    = "REGIME_STRESS"     # Stress regime detected (high MOVE/VIX/breakeven)
    REGIME_SHIFT     = "REGIME_SHIFT"      # Structural regime change underway
    REGIME_UNKNOWN   = "REGIME_UNKNOWN"    # Insufficient data to classify regime

    SIGNAL_BUY       = "SIGNAL_BUY"        # Directional signal: buy gold
    SIGNAL_SELL      = "SIGNAL_SELL"       # Directional signal: reduce/sell gold
    SIGNAL_HOLD      = "SIGNAL_HOLD"       # No directional change warranted

    # ── Group 4: Uncertainty / confidence codes ───────────────────────────
    # Emitted when the engine declines to act due to uncertainty constraints.

    UNCERTAINTY_HIGH  = "UNCERTAINTY_HIGH" # uncertainty > U_max → no execution
    CONFIDENCE_LOW    = "CONFIDENCE_LOW"   # confidence < C_min → no execution

    # ── Group 5: Operational / infrastructure codes ───────────────────────
    # Emitted by Layer-4 execution orchestration or operational monitoring.
    # Layer-2 and Layer-3 must not emit these. Defined here for completeness.

    EXECUTION_BLOCKED = "EXECUTION_BLOCKED"   # Execution layer blocked (kill switch, etc.)
    EXECUTION_PAPER   = "EXECUTION_PAPER"     # Paper-mode only; no live execution
    EXECUTION_REDUCED = "EXECUTION_REDUCED"   # Reduced sizing only; liquidity constraint

    # ── Validation helpers ────────────────────────────────────────────────

    @classmethod
    def validate(cls, value: Union[str, "ReasonCode"]) -> "ReasonCode":
        """
        Return the ReasonCode for a string value, or raise ValueError.

        Use this at execution boundary validation to reject free-text values:
            code = ReasonCode.validate(decision_packet["reason_code"])

        Args:
            value: A string matching one of the enum values, or a ReasonCode.

        Returns:
            The matching ReasonCode enum member.

        Raises:
            ValueError: If `value` is not a valid ReasonCode.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError:
            valid = sorted(m.value for m in cls)
            raise ValueError(
                f"{value!r} is not a valid ReasonCode. "
                f"Valid values: {valid}"
            )

    @classmethod
    def values(cls) -> list:
        """Return sorted list of all valid reason code strings."""
        return sorted(m.value for m in cls)

    @classmethod
    def data_layer_codes(cls) -> list:
        """Return codes that belong to Group 0 (Layer-2 data layer)."""
        return [cls.DATA_OK, cls.DATA_STALE, cls.DATA_MISSING, cls.DATA_FORCED]

    @classmethod
    def bootstrap_required(cls) -> list:
        """Return the minimum set required for Layer-3 Phase 1 bootstrap."""
        return [cls.NO_SIGNAL, cls.NO_TRADE]


# ---------------------------------------------------------------------------
# Guards schema documentation
# ---------------------------------------------------------------------------

# The `guards` dict in every snapshot JSON has this shape.
# Layer-2 populates `data_ok` based on quality gate outcome.
# All other guards are stubbed at the Layer-2 boundary — they are evaluated
# or overridden by Layer-3 (Supervisor Engine) and Layer-4 (execution layer).
#
# Layer-3 MUST check guards.data_ok == True before consuming snapshot values.
# Layer-3 MUST emit VETO_DATA if data_ok is False and action != NOTHING.
#
GUARDS_SCHEMA = {
    "data_ok":        bool,   # True if quality gate PASS and not forced
    "idempotent_ok":  bool,   # True if this snapshot_id has not already been acted on
    "cooldown_ok":    bool,   # True if not within a post-trade cooldown window
    "risk_ok":        bool,   # True if position and drawdown caps are not exceeded
    "supervisor_veto": bool,  # False unless Supervisor Engine sets an explicit block
}

# Stub values Layer-2 emits for guards it cannot evaluate.
# Layer-3 must override these with real evaluations before execution.
GUARDS_L2_STUB = {
    "data_ok":        None,   # Computed from quality gate — see build_guards()
    "idempotent_ok":  True,   # Layer-3 responsibility: check snapshot_id not yet acted on
    "cooldown_ok":    True,   # Layer-3/4 responsibility: check cooldown state
    "risk_ok":        True,   # Layer-3/4 responsibility: check position + drawdown caps
    "supervisor_veto": False, # Layer-3 responsibility: Supervisor Engine evaluation
}


def build_guards(
    snapshot_ok: bool,
    forced: bool,
    missing_tier1: bool = False,
) -> dict:
    """
    Build the `guards` dict for a snapshot JSON.

    Layer-2 is responsible for `data_ok` only.
    All other guards are emitted as their Layer-2 stub values and must be
    re-evaluated by Layer-3 before any execution decision is made.

    Args:
        snapshot_ok:    Quality gate verdict (True = PASS).
        forced:         True if snapshot was published with --force.
        missing_tier1:  True if any Tier-1 series is missing from the payload.

    Returns:
        Guards dict with data_ok computed and all other fields stubbed.
    """
    # data_ok is false if:
    #   - quality gate failed (any Tier-1 stale)
    #   - snapshot was forced (gate bypassed — data integrity not guaranteed)
    #   - any Tier-1 series is missing from the payload
    data_ok = snapshot_ok and not forced and not missing_tier1

    return {
        "data_ok":        data_ok,
        "idempotent_ok":  GUARDS_L2_STUB["idempotent_ok"],
        "cooldown_ok":    GUARDS_L2_STUB["cooldown_ok"],
        "risk_ok":        GUARDS_L2_STUB["risk_ok"],
        "supervisor_veto": GUARDS_L2_STUB["supervisor_veto"],
    }
