# AI OS V1.0 Architecture

## Product loop
CAPTURE → UNDERSTAND → REVIEW → CONNECT → ANALYZE → DECIDE → ACT → LEARN

## Core principles
1. Markdown is the portable source of truth.
2. SQLite is the operational index, not the canonical knowledge store.
3. AI mutations are proposed first and require human review.
4. Modules are independently enableable/disableable.
5. Provider adapters keep the AI layer model-agnostic.
6. Local-first by default; cloud services are explicit dependencies.

## Planned modules
- Inbox
- People
- Events
- Organizations
- Factions / groups
- Places
- Timeline
- Concepts
- Projects
- Intelligence
- Decisions
- Learning
- Life

## Next engineering slices
1. Real Markdown scanner + frontmatter parser.
2. Review queue persistence in SQLite.
3. AI provider adapter (DeepSeek/OpenAI/Qwen/etc.).
4. Search + entity extraction + relationship proposals.
5. Tauri shell and Windows installer.
6. Audit log and module registry.
