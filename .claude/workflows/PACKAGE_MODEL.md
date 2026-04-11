# Package Model

## Structure

```
.claude/workflows/
  system-orchestration.yaml       # compiled entry manifest (root)
  PACKAGE_MODEL.md                # this file

  packages/
    execution-metadata.yaml       # schema/predicate/artifact contract versions
    constitution.yaml             # CLAUDE.md normative mapping
    manifest.yaml                 # orchestration manifest self-reference
    predicates.yaml               # scope predicate definitions
    skills.yaml                   # skill inventory with step/artifact bindings
    hooks.yaml                    # hook definitions with checks and gating logic
    subagents.yaml                # subagent declarations with trigger conditions
    agents.yaml                   # agent definitions — primary workflow step executors
    artifacts.yaml                # required inputs, expected outputs, producer ownership
    interpretation-policy.yaml    # claim routing and conflict resolution rules
    stage-gates.yaml              # phase gate definitions with enforcement checks
    blocking-conditions.yaml      # blocking condition registry
    verification-ledger.yaml      # ledger structure, fields, and update rules
    workflow-steps.yaml           # full DAG node list (all five layers)
```

## Root Manifest Assembly Model

`system-orchestration.yaml` is the sole entrypoint. It contains no governance content of its own — only assembly metadata, the package list, validation expectations, and compatibility metadata.

The DAG runner assembles the spec as follows:

1. Load `system-orchestration.yaml`.
2. Read `assembly.packages` in declared order.
3. For each entry: load the package file, read its `data` block, merge into the section named by `section`.
4. Run all `validation_expectations` against the assembled spec.
5. If any validation fails: halt immediately (fail-closed).
6. Compile the DAG from the assembled `workflow` section.

## Package Loading Order

```
1.  execution_metadata
2.  constitution
3.  orchestration_manifest
4.  scope_predicates
5.  skills
6.  hooks
7.  subagents
8.  agents
9.  artifacts
10. interpretation_policy
11. stage_gates
12. blocking_conditions
13. verification_ledger
14. workflow
```

Order is explicit and deterministic. The runner must not rely on filesystem ordering.

## Package File Format

Each package file contains exactly three fields:

```yaml
section: <section_name>   # owned section key in the assembled spec
version: "1.0"            # package schema version
data: ...                 # content merged into that section
```

## Section Ownership

| Package file                   | Owns section             |
|-------------------------------|--------------------------|
| execution-metadata.yaml        | execution_metadata       |
| constitution.yaml              | constitution             |
| manifest.yaml                  | orchestration_manifest   |
| predicates.yaml                | scope_predicates         |
| skills.yaml                    | skills                   |
| hooks.yaml                     | hooks                    |
| subagents.yaml                 | subagents                |
| agents.yaml                    | agents                   |
| artifacts.yaml                 | artifacts                |
| interpretation-policy.yaml     | interpretation_policy    |
| stage-gates.yaml               | stage_gates              |
| blocking-conditions.yaml       | blocking_conditions      |
| verification-ledger.yaml       | verification_ledger      |
| workflow-steps.yaml            | workflow                 |

Each section is owned by exactly one package. No cross-package duplication.

## DAG Compiler Notes

- Workflow step IDs are the DAG node keys (`id` field in each step).
- `depends_on` lists define directed edges. Must be acyclic.
- `component: skill:<name>` binds the step to a skill declared in `skills.yaml` by `name`.
- `component: stage_gates` binds to the gates in `stage-gates.yaml` via the step's `inputs.stage_gates` reference.
- `component: subagents` dispatches via `audit_dispatch` conditions in the step.
- `component: hooks` synthesizes hook signals via `consumes_hook_signals`.
- `agent_binding: <name>` binds the step to an agent declared in `agents.yaml` by `name`. The agent is the execution unit; the skill (via `component`) provides behavioral instructions.
- Agent names in `agent_binding` fields must resolve to entries in `agents`.
- `component: constitution` is a reserved executor for the `load-context` step only.
- Predicates in `condition`, `skip_if`, and `requires_if` fields must resolve to entries in `scope_predicates`.
- Blocking condition ids in `raises` and `validates` must resolve to entries in `blocking-conditions`.
- Subagent names in `escalates_to[*].invoke` must resolve to entries in `subagents`.
- Hook names in `reinforced_by_hook` must resolve to entries in `hooks`.
