# Agent Skills

Hermes Agent skills for the secontrol project. These files are the source of truth — Hermes loads them from `~/.hermes/skills/` at runtime, but the canonical copy lives here in git.

## Structure

```
agent/
  REPO_GUIDE.md          # Developer guide: source layout, adding devices, tests, architecture
  skills/
    se-projection-builder.md   # Building blocks via projector + nanobot welder
```

## Sync with Hermes

Skills are installed to the Hermes runtime directory at `~/.hermes/skills/` (not in repo). To sync from git to Hermes, copy the file to the appropriate category/name subdirectory. To export from Hermes back to git, copy the SKILL.md back to `agent/skills/`.

## Adding new skills

1. Create a `.md` file in `agent/skills/` with YAML frontmatter:
   ```yaml
   ---
   name: skill-name
   description: "Short description"
   tags: [tag1, tag2]
   version: 1
   ---
   ```
2. Add the body with instructions, code examples, pitfalls
3. Commit to git
