"""Phase 0 — CLI Behavior Probe for --json-schema and --bare flags.

Runs 4 Claude CLI subprocess invocations with controlled inputs and
captures full stdout/stderr for each.  Results are written to
scripts/probe_results.json for manual inspection before any production
code depends on these flags.

No production code is modified by this script.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

RESULTS_PATH = Path(__file__).parent / "probe_results.json"

SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "artifacts": {
            "type": "object",
            "properties": {
                "test_artifact": {"type": "object"},
            },
            "required": ["test_artifact"],
        },
    },
    "required": ["artifacts"],
})

PROMPT = (
    'Respond with a JSON object: '
    '{"artifacts": {"test_artifact": {"produced_by": "probe", "value": "hello"}}}'
)

TIMEOUT_S = 60


def _run_probe(label: str, cmd: list[str]) -> dict:
    """Run a single probe and return structured results."""
    print(f"\n{'='*60}")
    print(f"Probe {label}: {' '.join(cmd[:6])}...")
    print(f"{'='*60}")

    result: dict = {"label": label, "command": cmd}
    t0 = time.monotonic()

    try:
        proc = subprocess.run(
            cmd,
            input=PROMPT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            encoding="utf-8",
        )
        latency_ms = (time.monotonic() - t0) * 1000.0
        result["returncode"] = proc.returncode
        result["stdout_length"] = len(proc.stdout)
        result["stderr_length"] = len(proc.stderr)
        result["stderr_first_500"] = proc.stderr[:500]
        result["latency_ms"] = round(latency_ms, 1)

        # Parse outer envelope
        try:
            envelope = json.loads(proc.stdout)
            result["envelope_keys"] = sorted(envelope.keys()) if isinstance(envelope, dict) else None
            result["envelope_is_error"] = envelope.get("is_error") if isinstance(envelope, dict) else None

            raw_result = envelope.get("result", "") if isinstance(envelope, dict) else ""
            result["result_type"] = type(raw_result).__name__
            result["result_first_500"] = (
                raw_result[:500] if isinstance(raw_result, str)
                else str(raw_result)[:500]
            )

            # Capture structured_output field if present
            structured = envelope.get("structured_output") if isinstance(envelope, dict) else None
            if structured is not None:
                result["structured_output_type"] = type(structured).__name__
                result["structured_output_first_500"] = str(structured)[:500]
                if isinstance(structured, dict):
                    result["structured_output_keys"] = sorted(structured.keys())
                    # Check if it has our expected artifact shape
                    result["structured_output_has_artifacts"] = "artifacts" in structured

            # Try parsing inner result as JSON
            if isinstance(raw_result, str):
                try:
                    inner = json.loads(raw_result)
                    result["inner_json_parse"] = "SUCCESS"
                    result["inner_json_keys"] = sorted(inner.keys()) if isinstance(inner, dict) else None
                    result["inner_json_type"] = type(inner).__name__
                except (json.JSONDecodeError, TypeError):
                    result["inner_json_parse"] = "FAILED"
                    result["result_starts_with_brace"] = raw_result.strip().startswith("{")
            elif isinstance(raw_result, dict):
                # result field is already a parsed object (not a string)
                result["inner_json_parse"] = "ALREADY_PARSED"
                result["inner_json_keys"] = sorted(raw_result.keys())
                result["inner_json_type"] = "dict"

            # Check for structured_output or similar fields
            if isinstance(envelope, dict):
                extra_fields = [
                    k for k in envelope.keys()
                    if k not in ("type", "subtype", "is_error", "result",
                                 "duration_ms", "duration_api_ms", "num_turns",
                                 "stop_reason", "session_id", "total_cost_usd",
                                 "usage", "model")
                ]
                result["extra_envelope_fields"] = extra_fields

            result["usage"] = envelope.get("usage", {}) if isinstance(envelope, dict) else {}

        except (json.JSONDecodeError, TypeError) as exc:
            result["envelope_parse"] = f"FAILED: {exc}"
            result["stdout_first_500"] = proc.stdout[:500]

    except subprocess.TimeoutExpired:
        latency_ms = (time.monotonic() - t0) * 1000.0
        result["error"] = f"TimeoutExpired after {TIMEOUT_S}s"
        result["latency_ms"] = round(latency_ms, 1)
    except OSError as exc:
        result["error"] = f"OSError: {exc}"

    # Print summary
    print(f"  returncode: {result.get('returncode', 'N/A')}")
    print(f"  result_type: {result.get('result_type', 'N/A')}")
    print(f"  inner_json_parse: {result.get('inner_json_parse', 'N/A')}")
    print(f"  envelope_keys: {result.get('envelope_keys', 'N/A')}")
    if result.get("extra_envelope_fields"):
        print(f"  extra_envelope_fields: {result['extra_envelope_fields']}")
    print(f"  latency_ms: {result.get('latency_ms', 'N/A')}")

    return result


def main() -> int:
    base_cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--no-session-persistence",
        "--tools", "",
    ]

    probes = {
        "A": base_cmd + ["--json-schema", SCHEMA],
        "B": base_cmd + ["--bare", "--json-schema", SCHEMA],
        "C": base_cmd,  # Control: no schema, no bare
        "D": base_cmd + ["--bare"],  # bare only, no schema
    }

    results = {}
    for label, cmd in probes.items():
        results[label] = _run_probe(label, cmd)

    # Derive answers to the 8 validation questions
    answers: dict = {}
    a = results.get("A", {})
    b = results.get("B", {})
    c = results.get("C", {})
    d = results.get("D", {})

    # Check if structured_output field contains valid schema-constrained JSON
    has_structured = a.get("structured_output_type") is not None
    structured_has_artifacts = a.get("structured_output_has_artifacts", False)

    answers["Q1_json_schema_guarantees_valid_json"] = (
        a.get("inner_json_parse") == "SUCCESS"
        or (has_structured and structured_has_artifacts)
    )
    answers["Q1_detail"] = (
        "in_result" if a.get("inner_json_parse") == "SUCCESS"
        else ("in_structured_output" if has_structured else "NOT_FOUND")
    )
    answers["Q2_schema_result_in_result_or_separate_field"] = (
        "structured_output" if has_structured
        else ("result" if a.get("inner_json_parse") == "SUCCESS" else "unknown")
    )
    answers["Q3_result_field_type"] = a.get("result_type")
    answers["Q3_result_is_empty"] = not a.get("result_first_500", "").strip()
    answers["Q4_schema_eliminates_prose"] = (
        has_structured and not a.get("result_first_500", "").strip()
    )
    answers["Q5_bare_changes_envelope_shape"] = a.get("envelope_keys") != d.get("envelope_keys")
    answers["Q5_bare_returncode"] = d.get("returncode")
    answers["Q5_bare_error"] = d.get("result_first_500", "")[:200]
    answers["Q6_bare_plus_schema_works"] = (
        b.get("returncode") == 0
        and (b.get("inner_json_parse") == "SUCCESS" or b.get("structured_output_type") is not None)
    )
    answers["Q7_existing_parser_needs_adaptation"] = (
        has_structured and a.get("inner_json_parse") != "SUCCESS"
    )
    answers["Q7_detail"] = (
        "structured_output field requires new parse path"
        if has_structured and a.get("inner_json_parse") != "SUCCESS"
        else "existing parser works on result field"
    )
    answers["Q8_returncodes"] = {
        label: results[label].get("returncode") for label in "ABCD"
    }

    output = {
        "probe_results": results,
        "validation_answers": answers,
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n\nResults written to: {RESULTS_PATH}")
    print("\n--- Validation Answers ---")
    for k, v in answers.items():
        print(f"  {k}: {v}")

    # Gate check
    if not answers["Q1_json_schema_guarantees_valid_json"]:
        print("\n*** GATE FAILED: --json-schema does NOT guarantee valid JSON. ***")
        print("*** Phase 1 approach must be redesigned. ***")
        return 1

    if answers.get("Q1_detail") == "in_structured_output":
        print("\n*** GATE PASSED (ADAPTED): --json-schema output is in envelope.structured_output ***")
        print("*** Phase 1 must use _parse_structured_response() extracting from structured_output. ***")
    else:
        print("\n*** GATE PASSED: --json-schema constrains result to valid JSON. ***")
    print("*** Phase 1 may proceed. ***")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
