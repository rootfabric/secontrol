# secontrol — Agent Entry Point

`secontrol` is a Python SDK and command toolkit for controlling Space Engineers agents through the Redis gateway.

This file is the first file an AI agent must read before planning, running commands, editing code, or changing documentation.

---

## 0. Prime directive

Do not invent commands.

Before proposing or executing a mission plan:

1. Inspect existing commands.
2. Prefer `commands/` over `scripts/`.
3. Prefer `commands/` over `examples/organized/`.
4. Prefer existing playbooks and workflows over invented plans.
5. Validate that every script file in the plan exists.
6. Do not use `tmp/*.py` as operational commands.
7. Do not use `.refactor_backups/` or `.manual_refactor_backups/`.
8. Do not ask for manual help until all safe non-flight checks are completed.
9. If a task matches an existing pipeline, use that pipeline first.
10. If no existing command exists, say so and propose creating one. Do not fabricate a path.

---

## 1. Mandatory repository scan before planning

Before any non-trivial task, run or mentally follow this discovery order:

```bash
find commands -maxdepth 3 -type f | sort
find docs/playbooks docs/workflows docs/agent-playbook -type f 2>/dev/null | sort
grep -RniE "pipeline|пайплайн|добыча|mining|ice|hydrogen|dock|стыков|бур|ore|radar|navigation|production|refinery|projector" docs commands 2>/dev/null
```