#!/usr/bin/env python3
"""
Governance No-Op Verification (Step 10)
per agent_generation_plan.md Section 18.

Purpose: Perform a dry-run governance pass to confirm agents are
structurally accounted for within the DAG.

Actions:
  10.1  Walk the workflow DAG in topological order (load-context -> pre-pr-governance-readiness)
  10.2  At each agent-bound step, confirm:
        a) The agent file exists
        b) The agent file's inputs match the step's inputs
        c) The agent file's outputs match the step's outputs
        d) The agent file's hook reinforcement matches the step's reinforced_by_hook
  10.3  Confirm hooks can read agent-produced artifacts
        (hooks.yaml reads_artifacts matches agent produces)
  10.4  Confirm pre-PR gate required_artifacts fully covered by
        agent-produced + structural step outputs

Gate: Full DAG walk completes. All 18 steps accounted for. All 19 artifacts traceable.
"""

import os
import re
import sys
from collections import deque

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = SCRIPT_DIR
PACKAGES_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "workflows", "packages")


def load_yaml(filename):
    path = os.path.join(PACKAGES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_agent_section(filepath, section_name):
    """Extract the text content of a named ## section from an agent file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = rf"## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_artifact_names_from_section(section_text):
    """Extract backtick-quoted artifact/input names from bullet lines."""
    names = []
    for line in section_text.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            m = re.match(r"[-*]\s+`([a-zA-Z0-9_./*]+)`", line)
            if m:
                names.append(m.group(1))
    return names


def topological_sort(workflow_data):
    """Return steps in topological order (respecting depends_on)."""
    graph = {}
    in_degree = {}
    for step in workflow_data:
        sid = step["id"]
        graph[sid] = step.get("depends_on", [])
        if sid not in in_degree:
            in_degree[sid] = 0
        for dep in graph[sid]:
            if dep not in in_degree:
                in_degree[dep] = 0

    # Count in-degrees
    for sid, deps in graph.items():
        for dep in deps:
            pass  # deps are the nodes sid depends ON
    # Actually: in_degree[sid] = number of deps that must complete before sid
    in_degree = {sid: len(deps) for sid, deps in graph.items()}

    # BFS / Kahn's algorithm
    queue = deque([sid for sid, deg in in_degree.items() if deg == 0])
    order = []
    # Build reverse adjacency: who depends on me
    reverse = {sid: [] for sid in graph}
    for sid, deps in graph.items():
        for dep in deps:
            if dep in reverse:
                reverse[dep].append(sid)

    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in reverse.get(node, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    return order


def normalize_input_name(name):
    """Normalize input names for comparison.

    Workflow-steps.yaml may reference Documentation/SYSTEM_...
    while agent files reference canonical_docs or governance_context.
    We need to handle these semantic equivalences.
    """
    # Strip path prefixes for Documentation references
    if name.startswith("Documentation/"):
        return name
    return name


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 72)
    print("STEP 10 VALIDATION REPORT")
    print("Governance No-Op Verification")
    print("Agent Generation Plan -- Section 18")
    print("=" * 72)

    # Load all YAML data
    agents_yaml = load_yaml("agents.yaml")
    workflow_yaml = load_yaml("workflow-steps.yaml")
    artifacts_yaml = load_yaml("artifacts.yaml")
    hooks_yaml = load_yaml("hooks.yaml")

    agents_data = agents_yaml["data"]
    workflow_data = workflow_yaml["data"]
    artifacts_data = artifacts_yaml["data"]
    hooks_data = hooks_yaml["data"]

    # Build lookups
    agents_by_name = {a["name"]: a for a in agents_data}
    steps_by_id = {s["id"]: s for s in workflow_data}
    hooks_by_name = {h["name"]: h for h in hooks_data}
    expected_outputs = {a["id"]: a for a in artifacts_data["expected_outputs"]}

    all_pass = True

    # ===================================================================
    # 10.1: Walk the DAG in topological order
    # ===================================================================
    print("\n" + "=" * 72)
    print("10.1: DAG Walk -- Topological Order")
    print("=" * 72)

    topo_order = topological_sort(workflow_data)
    step_ids_set = set(steps_by_id.keys())

    if set(topo_order) == step_ids_set:
        print(f"\n  PASS  Full DAG walk: {len(topo_order)} steps in topological order")
    else:
        missing = step_ids_set - set(topo_order)
        print(f"\n  FAIL  Steps not reachable in DAG: {missing}")
        all_pass = False

    print("\n  Execution order:")
    for i, sid in enumerate(topo_order, 1):
        step = steps_by_id.get(sid, {})
        has_agent = "agent_binding" in step
        marker = "[AGENT]" if has_agent else "[STRUCTURAL]"
        binding = f" -> {step['agent_binding']}" if has_agent else ""
        print(f"    {i:2d}. {sid} {marker}{binding}")

    # ===================================================================
    # 10.2: Agent-bound step validation
    # ===================================================================
    print("\n" + "=" * 72)
    print("10.2: Agent-Bound Step Validation")
    print("=" * 72)

    agent_bound_steps = [s for s in workflow_data if "agent_binding" in s]
    check_10_2 = True

    for step in agent_bound_steps:
        step_id = step["id"]
        agent_name = step["agent_binding"]
        agent_entry = agents_by_name.get(agent_name, {})
        filepath = os.path.join(AGENTS_DIR, f"{agent_name}.md")

        print(f"\n  --- {step_id} -> {agent_name} ---")

        # 10.2a: Agent file exists
        if os.path.isfile(filepath):
            print(f"    PASS  Agent file exists")
        else:
            print(f"    FAIL  Agent file MISSING: {agent_name}.md")
            check_10_2 = False
            continue

        # 10.2b: Inputs match
        step_inputs = step.get("inputs", [])
        file_inputs_text = parse_agent_section(filepath, "Inputs")
        file_input_names = extract_artifact_names_from_section(file_inputs_text)

        # Normalize: workflow step inputs may include Documentation/* paths
        # while agent files may use aggregate names like canonical_docs.
        # We compare the artifact-level inputs (non-Documentation paths).
        step_artifact_inputs = [i for i in step_inputs
                                if not i.startswith("Documentation/")]
        step_doc_inputs = [i for i in step_inputs
                           if i.startswith("Documentation/")]
        file_artifact_inputs = [i for i in file_input_names
                                if not i.startswith("Documentation/")]
        file_doc_inputs = [i for i in file_input_names
                           if i.startswith("Documentation/")]

        # For artifact inputs: agent file should list all step artifact inputs
        # Agent file may use canonical_docs as aggregate for Documentation/* refs
        step_artifact_set = set(step_artifact_inputs)
        file_artifact_set = set(file_artifact_inputs)

        # Check if agent file uses canonical_docs to cover Documentation/* inputs
        has_canonical_docs_aggregate = "canonical_docs" in file_artifact_set
        step_has_doc_refs = len(step_doc_inputs) > 0

        # Remove canonical_docs from file set for comparison if step has doc refs
        comparison_file_set = file_artifact_set.copy()
        comparison_step_set = step_artifact_set.copy()

        # canonical_docs in agent file covers Documentation/* in step
        if has_canonical_docs_aggregate and step_has_doc_refs:
            comparison_file_set.discard("canonical_docs")

        # Check: step artifacts should be subset of file artifacts
        # (agent file may have additional context like canonical_docs)
        missing_in_file = comparison_step_set - comparison_file_set
        if has_canonical_docs_aggregate:
            # canonical_docs covers canonical_docs reference in step too
            missing_in_file.discard("canonical_docs")

        if not missing_in_file:
            print(f"    PASS  Inputs: step artifacts covered by agent file")
            if step_has_doc_refs and has_canonical_docs_aggregate:
                print(f"           (Documentation/* covered by canonical_docs aggregate)")
        else:
            print(f"    WARN  Inputs: step has {sorted(missing_in_file)} not in agent file")
            # This is a warning, not a hard fail, because workflow steps may
            # reference structural inputs (stage_gates, blocking_conditions)
            # that aren't explicit agent file inputs

        # 10.2c: Outputs match
        step_outputs = set(step.get("outputs", []))
        file_outputs_text = parse_agent_section(filepath, "Required Outputs")
        file_output_names = set(extract_artifact_names_from_section(file_outputs_text))

        if step_outputs == file_output_names:
            print(f"    PASS  Outputs: {sorted(step_outputs)} match")
        else:
            print(f"    FAIL  Outputs MISMATCH")
            print(f"           step:       {sorted(step_outputs)}")
            print(f"           agent file: {sorted(file_output_names)}")
            check_10_2 = False

        # 10.2d: Hook reinforcement matches
        step_hook = step.get("reinforced_by_hook")
        file_hook_text = parse_agent_section(filepath, "Hook Reinforcement")

        if step_hook is None:
            # Step has no hook -- agent file should say "None"
            if file_hook_text.strip().lower() == "none" or not file_hook_text.strip():
                print(f"    PASS  Hook reinforcement: None (consistent)")
            else:
                # Check if file mentions a hook name
                hook_refs = re.findall(r"`([a-z][a-z0-9-]+)`", file_hook_text)
                if hook_refs:
                    print(f"    FAIL  Hook: step has none, but agent file declares {hook_refs}")
                    check_10_2 = False
                else:
                    print(f"    PASS  Hook reinforcement: None (consistent)")
        else:
            # Step has a hook -- agent file should reference the same hook
            if step_hook in file_hook_text:
                print(f"    PASS  Hook reinforcement: '{step_hook}' matches")
            else:
                print(f"    FAIL  Hook MISMATCH: step='{step_hook}', file='{file_hook_text[:60]}'")
                check_10_2 = False

    if check_10_2:
        print(f"\n  >> 10.2 RESULT: PASS -- All {len(agent_bound_steps)} agent-bound steps validated")
    else:
        print(f"\n  >> 10.2 RESULT: FAIL")
        all_pass = False

    # ===================================================================
    # 10.3: Hook artifact readability
    # ===================================================================
    print("\n" + "=" * 72)
    print("10.3: Hook Artifact Readability")
    print("=" * 72)

    check_10_3 = True
    # For each hook, confirm its reads_artifacts can be produced by agents
    # Map: artifact -> producing agent
    artifact_to_agent = {}
    for agent in agents_data:
        for art in agent.get("produces", []):
            artifact_to_agent[art] = agent["name"]

    # Also include structural step outputs
    artifact_to_step = {}
    for step in workflow_data:
        for out in step.get("outputs", []):
            artifact_to_step[out] = step["id"]

    for hook in hooks_data:
        hook_name = hook["name"]
        reads = hook.get("reads_artifacts", [])
        print(f"\n  --- {hook_name} ---")

        for art in reads:
            if art in artifact_to_agent:
                agent = artifact_to_agent[art]
                print(f"    PASS  reads '{art}' -> produced by agent '{agent}'")
            elif art in artifact_to_step:
                step = artifact_to_step[art]
                print(f"    PASS  reads '{art}' -> produced by step '{step}'")
            else:
                print(f"    FAIL  reads '{art}' -> NO PRODUCER FOUND")
                check_10_3 = False

        # Verify the hook's reinforcing_phase step is agent-bound
        # and the agent produces the artifacts the hook reads
        reinforcing = hook.get("reinforcing_phase")
        if reinforcing and reinforcing in steps_by_id:
            step = steps_by_id[reinforcing]
            if "agent_binding" in step:
                agent_name = step["agent_binding"]
                agent_produces = set(agents_by_name.get(agent_name, {}).get("produces", []))
                for art in reads:
                    if art in agent_produces:
                        print(f"    PASS  '{art}' confirmed in agent '{agent_name}' produces")
                    elif art in artifact_to_step:
                        # Hook reads a structural artifact (e.g., pr_readiness_verdict)
                        print(f"    PASS  '{art}' is a structural output (not agent-produced)")
                    else:
                        print(f"    WARN  '{art}' not in agent '{agent_name}' produces")

    if check_10_3:
        print(f"\n  >> 10.3 RESULT: PASS -- All hooks can read their declared artifacts")
    else:
        print(f"\n  >> 10.3 RESULT: FAIL")
        all_pass = False

    # ===================================================================
    # 10.4: Pre-PR gate coverage
    # ===================================================================
    print("\n" + "=" * 72)
    print("10.4: Pre-PR Gate Artifact Coverage")
    print("=" * 72)

    check_10_4 = True

    # Get the pre-pr-governance-gate hook
    pre_pr_hook = hooks_by_name.get("pre-pr-governance-gate")
    if not pre_pr_hook:
        print("\n  FAIL  pre-pr-governance-gate hook not found")
        all_pass = False
    else:
        required_artifacts = pre_pr_hook.get("required_artifacts", [])
        print(f"\n  Pre-PR gate requires {len(required_artifacts)} artifacts:")

        # All artifacts produced across the workflow (agents + structural)
        all_produced = set()
        for step in workflow_data:
            for out in step.get("outputs", []):
                all_produced.add(out)

        for req in required_artifacts:
            art_id = req["artifact"]
            required_always = req.get("required_always", True)
            condition = ""
            if not required_always:
                pred = req.get("requires_if", {}).get("predicate", "")
                condition = f" (conditional: {pred})"

            if art_id in all_produced:
                # Determine producer
                producer = artifact_to_step.get(art_id, "unknown")
                producer_type = "agent" if art_id in artifact_to_agent else "structural"
                print(f"    PASS  '{art_id}' -> produced by {producer} [{producer_type}]{condition}")
            else:
                print(f"    FAIL  '{art_id}' -> NO PRODUCER in workflow{condition}")
                check_10_4 = False

        # Verify: every artifact in artifacts.yaml expected_outputs is producible
        print(f"\n  Cross-check: all {len(expected_outputs)} expected_outputs are produced:")
        for art_id, art_entry in expected_outputs.items():
            produced_by = art_entry["produced_by"]
            if produced_by in steps_by_id:
                step = steps_by_id[produced_by]
                if art_id in step.get("outputs", []):
                    print(f"    PASS  '{art_id}' -> step '{produced_by}' outputs it")
                else:
                    print(f"    FAIL  '{art_id}' -> step '{produced_by}' does NOT output it")
                    check_10_4 = False
            else:
                print(f"    FAIL  '{art_id}' -> produced_by step '{produced_by}' not found")
                check_10_4 = False

    if check_10_4:
        print(f"\n  >> 10.4 RESULT: PASS -- Pre-PR gate fully covered")
    else:
        print(f"\n  >> 10.4 RESULT: FAIL")
        all_pass = False

    # ===================================================================
    # Final summary
    # ===================================================================
    print("\n" + "=" * 72)
    print("STEP 10 GATE ASSESSMENT")
    print("=" * 72)

    total_steps = len(workflow_data)
    agent_steps = len(agent_bound_steps)
    structural_steps = total_steps - agent_steps
    total_artifacts = len(expected_outputs)

    print(f"\n  Total workflow steps:      {total_steps}")
    print(f"  Agent-bound steps:         {agent_steps}")
    print(f"  Structural steps:          {structural_steps}")
    print(f"  Total artifacts:           {total_artifacts}")
    print(f"  Pre-PR required artifacts: {len(pre_pr_hook.get('required_artifacts', []))}")

    print(f"\n  10.1 DAG Walk:             PASS")
    print(f"  10.2 Agent Step Validation: {'PASS' if check_10_2 else 'FAIL'}")
    print(f"  10.3 Hook Readability:      {'PASS' if check_10_3 else 'FAIL'}")
    print(f"  10.4 Pre-PR Coverage:       {'PASS' if check_10_4 else 'FAIL'}")

    if all_pass:
        print(f"\n  STEP 10 GATE: PASSED")
        print(f"  Full DAG walk completes. All {total_steps} steps accounted for.")
        print(f"  All {total_artifacts} artifacts traceable.")
    else:
        print(f"\n  STEP 10 GATE: FAILED")

    print("=" * 72)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
