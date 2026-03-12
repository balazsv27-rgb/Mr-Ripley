Task: initialise the the missing folders and files within the .claude/ folder. The newly created files should be left empty. Do not modify existing files.
Mr-Ripley/
├── CLAUDE.md                  # Project-wide instructions, conventions, workflow policy
├── .claude/
│   ├── settings.json          # Shared project settings
│   ├── settings.local.json    # Personal/local overrides, gitignored
│   ├── agents/                # Custom agents
│   │   ├── planner.md
│   │   ├── implementer.md
│   │   └── reviewer.md
│   ├── commands/              # Slash commands / project shortcuts
│   │   ├── workflows/
│   │   │   ├── plan.md
│   │   │   ├── work.md
│   │   │   └── review.md 
│   │   └── git/
│   │       ├── commit.md
│   │       └── pr.md
│   ├── hooks/                 # Event-driven scripts
│   │   ├── auto-format.sh
│   │   ├── run-tests.sh
│   │   └── security-scan.sh
│   ├── rules/                 # Auto-loaded conventions
│   │   ├── code-conventions.md
│   │   └── git-workflow.md
│   ├── skills/                # Reusable knowledge/capability modules
│   │   ├── refactor-module/
│   │   │   ├── SKILL.md
│   │   │   ├── reference.md
│   │   │   ├── checklists/
│   │   │   └── examples/
│   │   └── security-review/
│   │       ├── SKILL.md
│   │       └── checklists/
│   └── plans/                 # Saved plan files
│       ├── Review/
│       ├── Active/
│       └── Completed/
├── docs/
│   ├── brainstorms/           
│   ├── plans/                 
│   └── solutions/             
└── todos/                     
