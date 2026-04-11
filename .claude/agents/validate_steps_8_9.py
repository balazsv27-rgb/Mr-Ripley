#!/usr/bin/env python3
"""
Validate Subagent References (Step 8) and Structural Verification (Step 9)
per agent_generation_plan.md Section 18.

Step 8 -- Validate Subagent References:
  8.1  Every named subagent in agent Escalation sections exists in subagents.yaml
  8.2  Escalation conditions match agents.yaml escalation_targets
  8.3  Agent files do not describe performing subagent audit work
  8.4  Agents with no escalation targets correctly state "None"
  8.5  No agent file lists a subagent not declared in subagents.yaml
  8.6  No subagent is treated as a primary step executor in any agent file

Step 9 -- Run Structural Verification:
  9.1  every_agent_binding_resolves_to_declared_agent (re-run)
  9.2  every_agent_produces_declared_artifacts_only (re-run)
  9.3  every_agent_skill_binding_resolves_to_declared_skill
  9.4  No cycles in workflow dependencies
  9.5  .claude/agents/ contains exactly 14 agent files
  9.6  No YAML package was modified during agent file creation (git check)
"""

import os
import re
import subprocess
import sys

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = SCRIPT_DIR
PACKAGES_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "workflows", "packages")

NON_AGENT_FILES = {"AGENT_FILE_SCHEMA.md", "IMPLEMENTATION_MAPPING.md",
                    "VALIDATION_STEPS_6_7.md", "validate_steps_6_7.py",
                    "validate_steps_8_9.py"}


def load_yaml(filename):
    path = os.path.join(PACKAGES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_agent_md_files():
    files = []
    for f in os.listdir(AGENTS_DIR):
        if f.endswith(".md") and f not in NON_AGENT_FILES:
            files.append(f)
    return sorted(files)


def parse_agent_frontmatter(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None
    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None


def parse_agent_section(filepath, section_name):
    """Extract the text content of a named ## section from an agent file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = rf"## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_agent_required_outputs(filepath):
    """Extract artifact names from Required Outputs section (first backtick per bullet)."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(
        r"## Required Outputs\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL
    )
    if not match:
        return []
    artifacts = []
    for line in match.group(1).split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            m = re.match(r"[-*]\s+`([a-z_]+)`", line)
            if m:
                artifacts.append(m.group(1))
    return artifacts


def extract_subagent_names_from_escalation(escalation_text):
    """Extract subagent names mentioned in backticks from escalation section text."""
    if not escalation_text or escalation_text.strip().lower() == "none":
        return []
    # Match backtick-quoted names that look like subagent names (contain 'auditor', 'guardian', 'reconciler')
    # More generally: extract all backtick-quoted identifiers
    names = re.findall(r"`([a-z][a-z0-9_-]+)`", escalation_text)
    # Filter to only names that could be subagent names (contain hyphen, are multi-word)
    # Exclude artifact field names (contain underscores only, no hyphens)
    subagent_candidates = []
    for n in names:
        # Subagent names use hyphens; field names use underscores
        if "-" in n:
            subagent_candidates.append(n)
    return subagent_candidates


def detect_audit_language(filepath):
    """Check if an agent file describes performing audit work itself."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove the Escalation section to avoid false positives from dispatch descriptions
    content_no_escalation = re.sub(
        r"## Escalation\s*\n.*?(?=\n## |\Z)", "", content, flags=re.DOTALL
    )

    # Patterns indicating the agent performs audit work itself
    audit_patterns = [
        r"this agent performs? (?:deep |detailed )?audit",
        r"this agent investigates?",
        r"this agent conducts? (?:deep |detailed )?audit",
        r"perform(?:s|ing)? the audit work",
        r"conduct(?:s|ing)? (?:deep |the )?audit",
    ]
    for pattern in audit_patterns:
        if re.search(pattern, content_no_escalation, re.IGNORECASE):
            return True
    return False


def check_dag_cycles(workflow_data):
    """Check for cycles in the workflow DAG using DFS."""
    # Build adjacency list from depends_on
    graph = {}
    for step in workflow_data:
        step_id = step["id"]
        graph[step_id] = step.get("depends_on", [])

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}
    cycle_path = []

    def dfs(node):
        color[node] = GRAY
        for dep in graph.get(node, []):
            if dep not in color:
                continue  # reference to non-existent node (separate error)
            if color[dep] == GRAY:
                cycle_path.append(f"{node} -> {dep}")
                return True
            if color[dep] == WHITE and dfs(dep):
                cycle_path.append(f"{node} -> {dep}")
                return True
        color[node] = BLACK
        return False

    for node in graph:
        if color[node] == WHITE:
            if dfs(node):
                return True, cycle_path
    return False, []


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 72)
    print("STEP 8 & 9 VALIDATION REPORT")
    print("Agent Generation Plan -- Section 18")
    print("=" * 72)

    # Load YAML data
    agents_yaml = load_yaml("agents.yaml")
    workflow_yaml = load_yaml("workflow-steps.yaml")
    artifacts_yaml = load_yaml("artifacts.yaml")
    subagents_yaml = load_yaml("subagents.yaml")
    skills_yaml = load_yaml("skills.yaml")

    agents_data = agents_yaml["data"]
    workflow_data = workflow_yaml["data"]
    artifacts_data = artifacts_yaml["data"]
    subagents_data = subagents_yaml["data"]
    skills_data = skills_yaml["data"]

    # Build lookups
    agents_by_name = {a["name"]: a for a in agents_data}
    subagents_by_name = {s["name"]: s for s in subagents_data}
    skills_by_name = {s["name"]: s for s in skills_data}
    steps_by_id = {s["id"]: s for s in workflow_data}

    binding_to_step = {}
    for s in workflow_data:
        if "agent_binding" in s:
            binding_to_step[s["agent_binding"]] = s["id"]

    expected_outputs = {
        a["id"]: a for a in artifacts_data["expected_outputs"]
    }

    agent_md_files = get_agent_md_files()
    agent_md_names = {f.replace(".md", "") for f in agent_md_files}

    all_pass = True
    step8_pass = True
    step9_pass = True

    # ===================================================================
    # STEP 8 -- Validate Subagent References
    # ===================================================================
    print("\n" + "=" * 72)
    print("STEP 8 -- Validate Subagent References")
    print("=" * 72)

    # 8.1: Every named subagent in Escalation sections exists in subagents.yaml
    print("\n--- 8.1: escalation subagents -> subagents.yaml ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        esc_text = parse_agent_section(filepath, "Escalation")
        subagent_refs = extract_subagent_names_from_escalation(esc_text)

        if not subagent_refs:
            continue

        for sa in subagent_refs:
            if sa in subagents_by_name:
                print(f"  PASS  {name} -> {sa}: exists in subagents.yaml")
            else:
                print(f"  FAIL  {name} -> {sa}: NOT in subagents.yaml")
                step8_pass = False

    # 8.2: Escalation targets in agent files match agents.yaml escalation_targets
    print("\n--- 8.2: agent file escalation == agents.yaml escalation_targets ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        esc_text = parse_agent_section(filepath, "Escalation")
        file_subagents = set(extract_subagent_names_from_escalation(esc_text))

        # Get agents.yaml escalation targets
        agent_entry = agents_by_name.get(name, {})
        yaml_targets = agent_entry.get("escalation_targets", [])
        yaml_subagents = set()
        for t in yaml_targets:
            if isinstance(t, dict) and "subagent" in t:
                yaml_subagents.add(t["subagent"])
            elif isinstance(t, str):
                yaml_subagents.add(t)

        if file_subagents == yaml_subagents:
            if file_subagents:
                print(f"  PASS  {name}: file={sorted(file_subagents)} matches agents.yaml")
            else:
                print(f"  PASS  {name}: no escalation targets (consistent)")
        else:
            print(f"  FAIL  {name}: MISMATCH")
            print(f"         agent file:  {sorted(file_subagents)}")
            print(f"         agents.yaml: {sorted(yaml_subagents)}")
            step8_pass = False

    # 8.3: Agent files do not describe performing subagent audit work
    print("\n--- 8.3: no agent performs subagent audit work ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        if detect_audit_language(filepath):
            print(f"  FAIL  {name}: describes performing audit work (role confusion)")
            step8_pass = False
        else:
            print(f"  PASS  {name}: no audit work claimed")

    # 8.4: Agents with no escalation targets correctly state "None"
    print("\n--- 8.4: agents without targets state 'None' ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        agent_entry = agents_by_name.get(name, {})
        yaml_targets = agent_entry.get("escalation_targets", [])

        if not yaml_targets:
            esc_text = parse_agent_section(filepath, "Escalation")
            if esc_text.strip().lower() == "none":
                print(f"  PASS  {name}: correctly states 'None'")
            elif not esc_text.strip():
                print(f"  WARN  {name}: escalation section empty (expected 'None')")
            else:
                subagent_refs = extract_subagent_names_from_escalation(esc_text)
                if subagent_refs:
                    print(f"  FAIL  {name}: should be 'None' but lists: {subagent_refs}")
                    step8_pass = False
                else:
                    print(f"  PASS  {name}: no subagent references (acceptable)")

    # 8.5: No agent file lists a subagent not declared in subagents.yaml
    print("\n--- 8.5: no undeclared subagent references ---")
    undeclared = []
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        esc_text = parse_agent_section(filepath, "Escalation")
        subagent_refs = extract_subagent_names_from_escalation(esc_text)
        for sa in subagent_refs:
            if sa not in subagents_by_name:
                undeclared.append((name, sa))
                print(f"  FAIL  {name} references undeclared subagent '{sa}'")
                step8_pass = False
    if not undeclared:
        print(f"  PASS  Zero undeclared subagent references")

    # 8.6: No subagent is treated as a primary step executor
    print("\n--- 8.6: no subagent treated as primary step executor ---")
    # Check: no subagent name appears as agent_binding in workflow-steps.yaml
    # Check: no subagent name appears in agents.yaml
    subagent_names = set(subagents_by_name.keys())
    agent_names = set(agents_by_name.keys())
    binding_names = set(binding_to_step.keys())

    overlap_agents = subagent_names & agent_names
    overlap_bindings = subagent_names & binding_names

    if overlap_agents:
        for s in sorted(overlap_agents):
            print(f"  FAIL  Subagent '{s}' also declared as agent in agents.yaml")
            step8_pass = False
    if overlap_bindings:
        for s in sorted(overlap_bindings):
            print(f"  FAIL  Subagent '{s}' used as agent_binding in workflow-steps.yaml")
            step8_pass = False
    if not overlap_agents and not overlap_bindings:
        print(f"  PASS  Zero subagents treated as primary step executors")

    # Also check: no agent file describes a subagent as performing primary step work
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        bound_step_text = parse_agent_section(filepath, "Bound Workflow Step")
        # Verify the bound step text doesn't reference a subagent as executor
        for sa_name in subagent_names:
            if sa_name in bound_step_text:
                print(f"  FAIL  {name}: Bound Workflow Step references subagent '{sa_name}'")
                step8_pass = False

    # Step 8 gate
    print("\n" + "-" * 72)
    if step8_pass:
        print("STEP 8 GATE: PASSED -- All escalation references valid. "
              "No agent-subagent role confusion.")
    else:
        print("STEP 8 GATE: FAILED")
        all_pass = False

    # ===================================================================
    # STEP 9 -- Run Structural Verification
    # ===================================================================
    print("\n" + "=" * 72)
    print("STEP 9 -- Run Structural Verification")
    print("=" * 72)

    # 9.1: every_agent_binding_resolves_to_declared_agent (re-run)
    print("\n--- 9.1: every_agent_binding_resolves_to_declared_agent ---")
    check_91 = True
    for agent_name, step_id in sorted(binding_to_step.items()):
        if agent_name not in agents_by_name:
            print(f"  FAIL  {agent_name} -> step '{step_id}' -> NOT in agents.yaml")
            check_91 = False
        filepath = os.path.join(AGENTS_DIR, f"{agent_name}.md")
        if not os.path.isfile(filepath):
            print(f"  FAIL  {agent_name}.md MISSING")
            check_91 = False
    if check_91:
        print(f"  PASS  All {len(binding_to_step)} agent bindings resolve")
    else:
        step9_pass = False

    # 9.2: every_agent_produces_declared_artifacts_only (re-run)
    print("\n--- 9.2: every_agent_produces_declared_artifacts_only ---")
    check_92 = True
    for agent in agents_data:
        name = agent["name"]
        for artifact_id in agent.get("produces", []):
            if artifact_id not in expected_outputs:
                print(f"  FAIL  {name} produces '{artifact_id}' not in artifacts.yaml")
                check_92 = False
    if check_92:
        print(f"  PASS  All agent produces entries are declared artifacts")
    else:
        step9_pass = False

    # 9.3: every_agent_skill_binding_resolves_to_declared_skill
    print("\n--- 9.3: every_agent_skill_binding_resolves_to_declared_skill ---")
    check_93 = True
    for agent in agents_data:
        name = agent["name"]
        for skill_name in agent.get("skill_bindings", []):
            if skill_name in skills_by_name:
                print(f"  PASS  {name} -> skill '{skill_name}' exists")
            else:
                print(f"  FAIL  {name} -> skill '{skill_name}' NOT in skills.yaml")
                check_93 = False
        if not agent.get("skill_bindings"):
            print(f"  PASS  {name} -> no skill binding (dispatcher agent)")
    if not check_93:
        step9_pass = False

    # 9.4: No cycles in workflow dependencies
    print("\n--- 9.4: no cycles in workflow DAG ---")
    has_cycle, cycle_info = check_dag_cycles(workflow_data)
    if has_cycle:
        print(f"  FAIL  Cycle detected: {cycle_info}")
        step9_pass = False
    else:
        print(f"  PASS  DAG has no cycles ({len(workflow_data)} steps verified)")

    # 9.5: .claude/agents/ contains exactly 14 agent files
    print("\n--- 9.5: exactly 14 agent files ---")
    agent_count = len(agent_md_files)
    if agent_count == 14:
        print(f"  PASS  Exactly 14 agent files found")
    else:
        print(f"  FAIL  Expected 14, found {agent_count}: {agent_md_files}")
        step9_pass = False

    # Also verify no extra non-agent .md files that aren't in the exclusion list
    all_md = [f for f in os.listdir(AGENTS_DIR) if f.endswith(".md")]
    non_agent_md = [f for f in all_md if f not in NON_AGENT_FILES
                    and f.replace(".md", "") not in agents_by_name]
    if non_agent_md:
        print(f"  WARN  Unrecognized .md files in agents dir: {non_agent_md}")

    # Also verify no .py files other than validation scripts
    py_files = [f for f in os.listdir(AGENTS_DIR) if f.endswith(".py")]
    known_py = {"validate_steps_6_7.py", "validate_steps_8_9.py"}
    unknown_py = [f for f in py_files if f not in known_py]
    if unknown_py:
        print(f"  WARN  Unexpected .py files in agents dir: {unknown_py}")

    # 9.6: No YAML package was modified during agent file creation
    print("\n--- 9.6: YAML packages unmodified (git check) ---")
    yaml_files = [
        "agents.yaml", "workflow-steps.yaml", "artifacts.yaml",
        "subagents.yaml", "skills.yaml", "hooks.yaml",
        "blocking-conditions.yaml", "predicates.yaml",
        "stage-gates.yaml", "interpretation-policy.yaml"
    ]
    check_96 = True
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=os.path.dirname(PACKAGES_DIR)
        )
        changed_files = result.stdout.strip().split("\n") if result.stdout.strip() else []
        # Also check staged
        result2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=os.path.dirname(PACKAGES_DIR)
        )
        staged_files = result2.stdout.strip().split("\n") if result2.stdout.strip() else []
        all_changed = set(changed_files + staged_files)

        modified_yaml = []
        for yf in yaml_files:
            rel_path = f"packages/{yf}"
            full_rel = f".claude/workflows/packages/{yf}"
            if rel_path in all_changed or full_rel in all_changed or yf in all_changed:
                modified_yaml.append(yf)

        if modified_yaml:
            for yf in modified_yaml:
                print(f"  FAIL  {yf} was modified")
            check_96 = False
            step9_pass = False
        else:
            print(f"  PASS  No YAML packages modified (checked {len(yaml_files)} files)")
    except FileNotFoundError:
        print(f"  SKIP  git not available -- cannot verify YAML package integrity")

    # Additional structural checks from validation_expectations
    print("\n--- 9.7: additional structural invariants ---")

    # unique_workflow_step_ids
    step_ids = [s["id"] for s in workflow_data]
    if len(step_ids) == len(set(step_ids)):
        print(f"  PASS  unique_workflow_step_ids ({len(step_ids)} unique)")
    else:
        dupes = [s for s in step_ids if step_ids.count(s) > 1]
        print(f"  FAIL  Duplicate step IDs: {set(dupes)}")
        step9_pass = False

    # unique_artifact_producers
    producers = {}
    for a in artifacts_data["expected_outputs"]:
        aid = a["id"]
        prod = a["produced_by"]
        if aid in producers:
            print(f"  FAIL  Artifact '{aid}' has multiple producers: {producers[aid]}, {prod}")
            step9_pass = False
        else:
            producers[aid] = prod
    if len(producers) == len(artifacts_data["expected_outputs"]):
        print(f"  PASS  unique_artifact_producers ({len(producers)} unique)")

    # every_escalates_to_target_is_a_declared_subagent
    check_esc = True
    for step in workflow_data:
        for esc in step.get("escalates_to", []):
            target = esc.get("invoke", "")
            if target and target not in subagents_by_name:
                print(f"  FAIL  Step '{step['id']}' escalates to undeclared subagent '{target}'")
                check_esc = False
                step9_pass = False
        for esc in step.get("audit_dispatch", []):
            target = esc.get("invoke", "")
            if target and target not in subagents_by_name:
                print(f"  FAIL  Step '{step['id']}' dispatches undeclared subagent '{target}'")
                check_esc = False
                step9_pass = False
    if check_esc:
        print(f"  PASS  every_escalates_to_target_is_a_declared_subagent")

    # every_reinforced_by_hook_is_a_declared_hook
    hooks_yaml = load_yaml("hooks.yaml")
    hooks_by_name = {h["name"]: h for h in hooks_yaml["data"]}
    check_hooks = True
    for step in workflow_data:
        hook = step.get("reinforced_by_hook")
        if hook and hook not in hooks_by_name:
            print(f"  FAIL  Step '{step['id']}' reinforced_by_hook '{hook}' not in hooks.yaml")
            check_hooks = False
            step9_pass = False
    if check_hooks:
        print(f"  PASS  every_reinforced_by_hook_is_a_declared_hook")

    # dag_dependency_consistency -- every depends_on target exists as a step
    check_deps = True
    for step in workflow_data:
        for dep in step.get("depends_on", []):
            if dep not in steps_by_id:
                print(f"  FAIL  Step '{step['id']}' depends on non-existent step '{dep}'")
                check_deps = False
                step9_pass = False
    if check_deps:
        print(f"  PASS  dag_dependency_consistency (all depends_on targets exist)")

    # Step 9 gate
    print("\n" + "-" * 72)
    if step9_pass:
        print("STEP 9 GATE: PASSED -- Structural verification passes. No regressions.")
    else:
        print("STEP 9 GATE: FAILED")
        all_pass = False

    # Final summary
    print("\n" + "=" * 72)
    print("FINAL SUMMARY")
    print("=" * 72)
    print(f"  Agent files:          {len(agent_md_files)}")
    print(f"  Subagents declared:   {len(subagents_data)}")
    print(f"  Skills declared:      {len(skills_data)}")
    print(f"  Workflow steps:       {len(workflow_data)}")
    print(f"  Step 8 (Subagents):   {'PASSED' if step8_pass else 'FAILED'}")
    print(f"  Step 9 (Structural):  {'PASSED' if step9_pass else 'FAILED'}")
    print(f"  Overall:              {'ALL GATES PASSED' if all_pass else 'GATES FAILED'}")
    print("=" * 72)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
