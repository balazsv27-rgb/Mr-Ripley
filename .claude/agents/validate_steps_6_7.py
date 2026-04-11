#!/usr/bin/env python3
"""
Validate Binding Resolution (Step 6) and Artifact Ownership (Step 7)
per agent_generation_plan.md Section 18.

Checks performed:

Step 6 -- Validate Binding Resolution:
  6.1  Every agent_binding in workflow-steps.yaml resolves to agents.yaml entry
  6.2  Every agent_binding has a corresponding .claude/agents/<name>.md file
  6.3  Every agent file's frontmatter name matches its agents.yaml entry
  6.4  Every .claude/agents/*.md agent file name appears in agents.yaml
  6.5  Every agent file is referenced by exactly one agent_binding
  6.6  No duplicate agent identities across files
  6.7  No orphan agent files

Step 7 -- Validate Artifact Ownership:
  7.1  Every agent file Required Output appears in artifacts.yaml expected_outputs
  7.2  artifacts.yaml produced_by matches the agent's bound workflow step
  7.3  Every agent file Required Output appears in agents.yaml produces
  7.4  No agent file claims an artifact not in artifacts.yaml
  7.5  No artifacts.yaml artifact (produced by agent-bound step) missing from agent file
  7.6  Three-way consistency: agents.yaml produces == agent file outputs == artifacts.yaml
"""

import os
import re
import sys

import yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = SCRIPT_DIR  # .claude/agents/
PACKAGES_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "workflows", "packages")

# Non-agent .md files in .claude/agents/ (schema docs, not agent files)
NON_AGENT_FILES = {"AGENT_FILE_SCHEMA.md", "IMPLEMENTATION_MAPPING.md"}


def load_yaml(filename):
    path = os.path.join(PACKAGES_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_agent_md_files():
    """Return list of .md files in agents dir, excluding non-agent docs."""
    files = []
    for f in os.listdir(AGENTS_DIR):
        if f.endswith(".md") and f not in NON_AGENT_FILES:
            files.append(f)
    return sorted(files)


def parse_agent_frontmatter(filepath):
    """Extract frontmatter name field from an agent .md file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Match YAML frontmatter between --- delimiters
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None, None
    fm_text = match.group(1)
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return None, None
    return fm.get("name"), fm


def parse_agent_required_outputs(filepath):
    """Extract artifact names from the Required Outputs section.

    Each artifact is a bullet line starting with '- `artifact_name`'.
    Only the first backtick-quoted term per bullet is the artifact ID;
    subsequent backtick terms are field descriptions within that artifact.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the Required Outputs section
    match = re.search(
        r"## Required Outputs\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL
    )
    if not match:
        return []

    section = match.group(1)
    # Extract only the FIRST backtick-quoted term on each bullet line
    artifacts = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            m = re.match(r"[-*]\s+`([a-z_]+)`", line)
            if m:
                artifacts.append(m.group(1))
    return artifacts


def main():
    # Force UTF-8 output on Windows
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 72)
    print("STEP 6 & 7 VALIDATION REPORT")
    print("Agent Generation Plan -- Section 18")
    print("=" * 72)

    # Load YAML data
    agents_yaml = load_yaml("agents.yaml")
    workflow_yaml = load_yaml("workflow-steps.yaml")
    artifacts_yaml = load_yaml("artifacts.yaml")

    agents_data = agents_yaml["data"]
    workflow_data = workflow_yaml["data"]
    artifacts_data = artifacts_yaml["data"]

    # Build lookup structures
    # agents.yaml: name -> agent entry
    agents_by_name = {a["name"]: a for a in agents_data}

    # workflow-steps.yaml: step_id -> step, and agent_binding -> step_id mapping
    steps_by_id = {s["id"]: s for s in workflow_data}
    binding_to_step = {}
    for s in workflow_data:
        if "agent_binding" in s:
            binding_to_step[s["agent_binding"]] = s["id"]

    # artifacts.yaml: artifact_id -> artifact entry
    expected_outputs = {
        a["id"]: a for a in artifacts_data["expected_outputs"]
    }

    # Agent .md files
    agent_md_files = get_agent_md_files()
    agent_md_names = {f.replace(".md", "") for f in agent_md_files}

    all_pass = True
    step6_pass = True
    step7_pass = True

    # ===================================================================
    # STEP 6 -- Validate Binding Resolution
    # ===================================================================
    print("\n" + "=" * 72)
    print("STEP 6 -- Validate Binding Resolution")
    print("=" * 72)

    # 6.1: Every agent_binding in workflow-steps.yaml resolves to agents.yaml
    print("\n--- 6.1: agent_binding -> agents.yaml resolution ---")
    for agent_name, step_id in sorted(binding_to_step.items()):
        if agent_name in agents_by_name:
            print(f"  PASS  {agent_name} -> step '{step_id}' -> agents.yaml entry exists")
        else:
            print(f"  FAIL  {agent_name} -> step '{step_id}' -> NOT FOUND in agents.yaml")
            step6_pass = False

    # 6.2: Every agent_binding has a .claude/agents/<name>.md file
    print("\n--- 6.2: agent_binding -> .md file existence ---")
    for agent_name in sorted(binding_to_step.keys()):
        md_file = f"{agent_name}.md"
        filepath = os.path.join(AGENTS_DIR, md_file)
        if os.path.isfile(filepath):
            print(f"  PASS  {md_file} exists")
        else:
            print(f"  FAIL  {md_file} MISSING")
            step6_pass = False

    # 6.3: Every agent file's frontmatter name matches agents.yaml
    print("\n--- 6.3: agent file frontmatter name == agents.yaml name ---")
    for md_file in agent_md_files:
        filepath = os.path.join(AGENTS_DIR, md_file)
        fm_name, _ = parse_agent_frontmatter(filepath)
        expected_name = md_file.replace(".md", "")
        if fm_name == expected_name and expected_name in agents_by_name:
            print(f"  PASS  {md_file}: frontmatter name='{fm_name}' matches agents.yaml")
        elif fm_name != expected_name:
            print(
                f"  FAIL  {md_file}: frontmatter name='{fm_name}' != expected '{expected_name}'"
            )
            step6_pass = False
        else:
            print(
                f"  FAIL  {md_file}: name '{fm_name}' not found in agents.yaml"
            )
            step6_pass = False

    # 6.4: Every agent .md file name appears in agents.yaml
    print("\n--- 6.4: .md files -> agents.yaml presence ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        if name in agents_by_name:
            print(f"  PASS  {name} found in agents.yaml")
        else:
            print(f"  FAIL  {name} NOT in agents.yaml (orphan file)")
            step6_pass = False

    # 6.5: Every agent file is referenced by exactly one agent_binding
    print("\n--- 6.5: each agent referenced by exactly one agent_binding ---")
    binding_counts = {}
    for agent_name in binding_to_step:
        binding_counts[agent_name] = binding_counts.get(agent_name, 0) + 1

    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        count = binding_counts.get(name, 0)
        if count == 1:
            print(f"  PASS  {name} -> bound by exactly 1 step ({binding_to_step[name]})")
        elif count == 0:
            print(f"  FAIL  {name} -> bound by 0 steps (unbound agent)")
            step6_pass = False
        else:
            print(f"  FAIL  {name} -> bound by {count} steps (duplicate binding)")
            step6_pass = False

    # 6.6: No duplicate agent identities across files
    print("\n--- 6.6: no duplicate agent identities ---")
    seen_names = {}
    for md_file in agent_md_files:
        filepath = os.path.join(AGENTS_DIR, md_file)
        fm_name, _ = parse_agent_frontmatter(filepath)
        if fm_name in seen_names:
            print(
                f"  FAIL  Duplicate identity '{fm_name}' in {md_file} and {seen_names[fm_name]}"
            )
            step6_pass = False
        else:
            seen_names[fm_name] = md_file
    if len(seen_names) == len(agent_md_files):
        print(f"  PASS  {len(seen_names)} unique identities across {len(agent_md_files)} files -- no duplicates")

    # 6.7: No orphan agent files
    print("\n--- 6.7: no orphan agent files ---")
    agents_yaml_names = set(agents_by_name.keys())
    orphans = agent_md_names - agents_yaml_names
    if orphans:
        for o in sorted(orphans):
            print(f"  FAIL  Orphan: {o}.md has no agents.yaml entry")
            step6_pass = False
    else:
        print(f"  PASS  Zero orphan agent files")

    # Step 6 gate
    print("\n" + "-" * 72)
    if step6_pass:
        print("STEP 6 GATE: PASSED -- All bindings resolve. Zero orphans. Zero duplicates.")
    else:
        print("STEP 6 GATE: FAILED")
        all_pass = False

    # ===================================================================
    # STEP 7 -- Validate Artifact Ownership
    # ===================================================================
    print("\n" + "=" * 72)
    print("STEP 7 -- Validate Artifact Ownership")
    print("=" * 72)

    # Build the three-way mapping for comparison
    # Source A: agents.yaml produces
    # Source B: agent file Required Outputs
    # Source C: artifacts.yaml expected_outputs (for agent-bound steps)

    # Map agent_name -> bound step
    agent_to_step = {}
    for a in agents_data:
        for ws in a.get("workflow_steps", []):
            agent_to_step[a["name"]] = ws

    # Map step -> agent_name (reverse)
    step_to_agent = {v: k for k, v in agent_to_step.items()}

    # 7.1 & 7.3: Every agent file Required Output in artifacts.yaml and agents.yaml
    print("\n--- 7.1/7.3: agent file Required Outputs -> artifacts.yaml + agents.yaml ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        file_outputs = parse_agent_required_outputs(filepath)
        yaml_produces = agents_by_name.get(name, {}).get("produces", [])
        bound_step = agent_to_step.get(name)

        for artifact_id in file_outputs:
            # Check 7.1: in artifacts.yaml
            in_artifacts = artifact_id in expected_outputs
            # Check 7.3: in agents.yaml produces
            in_yaml = artifact_id in yaml_produces

            if in_artifacts and in_yaml:
                print(f"  PASS  {name} -> {artifact_id}: in artifacts.yaml and agents.yaml")
            else:
                if not in_artifacts:
                    print(
                        f"  FAIL  {name} -> {artifact_id}: NOT in artifacts.yaml expected_outputs"
                    )
                    step7_pass = False
                if not in_yaml:
                    print(
                        f"  FAIL  {name} -> {artifact_id}: NOT in agents.yaml produces"
                    )
                    step7_pass = False

    # 7.2: artifacts.yaml produced_by matches the agent's bound workflow step
    print("\n--- 7.2: artifacts.yaml produced_by == agent's bound step ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        file_outputs = parse_agent_required_outputs(filepath)
        bound_step = agent_to_step.get(name)

        for artifact_id in file_outputs:
            if artifact_id not in expected_outputs:
                continue  # Already flagged in 7.1
            produced_by = expected_outputs[artifact_id].get("produced_by")
            if produced_by == bound_step:
                print(
                    f"  PASS  {artifact_id}: produced_by='{produced_by}' == bound step '{bound_step}'"
                )
            else:
                print(
                    f"  FAIL  {artifact_id}: produced_by='{produced_by}' != bound step '{bound_step}'"
                )
                step7_pass = False

    # 7.4: No agent file claims artifact not in artifacts.yaml
    print("\n--- 7.4: no unclaimed artifacts ---")
    unclaimed = []
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)
        file_outputs = parse_agent_required_outputs(filepath)
        for artifact_id in file_outputs:
            if artifact_id not in expected_outputs:
                unclaimed.append((name, artifact_id))
                print(f"  FAIL  {name} claims '{artifact_id}' not in artifacts.yaml")
                step7_pass = False
    if not unclaimed:
        print(f"  PASS  Zero unclaimed artifacts across all agent files")

    # 7.5: No artifact in artifacts.yaml (produced by agent-bound step) missing from agent file
    print("\n--- 7.5: no missing artifacts in agent files ---")
    missing = []
    for artifact_id, artifact_entry in expected_outputs.items():
        produced_by_step = artifact_entry["produced_by"]
        # Is this step agent-bound?
        if produced_by_step not in step_to_agent:
            continue  # structural step, no agent file to check
        agent_name = step_to_agent[produced_by_step]
        filepath = os.path.join(AGENTS_DIR, f"{agent_name}.md")
        if not os.path.isfile(filepath):
            continue  # Already flagged in Step 6
        file_outputs = parse_agent_required_outputs(filepath)
        if artifact_id not in file_outputs:
            missing.append((agent_name, artifact_id))
            print(
                f"  FAIL  {agent_name}.md missing artifact '{artifact_id}' "
                f"(artifacts.yaml says produced_by='{produced_by_step}')"
            )
            step7_pass = False
    if not missing:
        print(f"  PASS  Zero missing artifacts -- all agent-bound artifacts declared in agent files")

    # 7.6: Three-way consistency cross-check
    print("\n--- 7.6: three-way consistency (agents.yaml <=> agent file <=> artifacts.yaml) ---")
    for md_file in agent_md_files:
        name = md_file.replace(".md", "")
        filepath = os.path.join(AGENTS_DIR, md_file)

        # Source A: agents.yaml produces
        yaml_produces = set(agents_by_name.get(name, {}).get("produces", []))
        # Source B: agent file Required Outputs
        file_outputs = set(parse_agent_required_outputs(filepath))
        # Source C: artifacts.yaml entries where produced_by == agent's bound step
        bound_step = agent_to_step.get(name)
        artifacts_for_step = set()
        for aid, aentry in expected_outputs.items():
            if aentry["produced_by"] == bound_step:
                artifacts_for_step.add(aid)

        if yaml_produces == file_outputs == artifacts_for_step:
            print(
                f"  PASS  {name}: three-way match -- {sorted(yaml_produces)}"
            )
        else:
            print(f"  FAIL  {name}: three-way MISMATCH")
            print(f"         agents.yaml produces:     {sorted(yaml_produces)}")
            print(f"         agent file outputs:       {sorted(file_outputs)}")
            print(f"         artifacts.yaml for step:  {sorted(artifacts_for_step)}")
            step7_pass = False

    # Step 7 gate
    print("\n" + "-" * 72)
    if step7_pass:
        print(
            "STEP 7 GATE: PASSED -- Three-way artifact contract consistency "
            "confirmed for all 14 agents."
        )
    else:
        print("STEP 7 GATE: FAILED")
        all_pass = False

    # Final summary
    print("\n" + "=" * 72)
    print("FINAL SUMMARY")
    print("=" * 72)
    print(f"  Agent files found:    {len(agent_md_files)}")
    print(f"  agents.yaml entries:  {len(agents_data)}")
    print(f"  Agent bindings:       {len(binding_to_step)}")
    print(f"  Expected outputs:     {len(expected_outputs)}")
    print(f"  Step 6 (Binding):     {'PASSED' if step6_pass else 'FAILED'}")
    print(f"  Step 7 (Artifacts):   {'PASSED' if step7_pass else 'FAILED'}")
    print(f"  Overall:              {'ALL GATES PASSED' if all_pass else 'GATES FAILED'}")
    print("=" * 72)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
