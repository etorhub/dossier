# Contributing to Dossier

Thank you for your interest in contributing. This project serves a general audience who want to read the news without the noise. Every contribution that improves content quality, accessibility, or reliability helps.

## Getting Started

- Read [README.md](README.md) for setup and [docs/TECH_STACK.md](docs/TECH_STACK.md) for project structure.
- Review [CLAUDE.md](CLAUDE.md) for architecture constraints and coding rules — these are non-negotiable.
- Check [docs/MVP_PLAN.md](docs/MVP_PLAN.md) for current priorities.

## Development Setup

```bash
git clone https://github.com/etorhub/dossier.git
cd dossier
docker-compose up -d
./scripts/fetch-news.sh
```

Admin: **admin@admin.com** / **admin**.

Run tests:

```bash
docker compose exec web pytest
```

## Code Standards

- **Python:** Type hints throughout. Use the db layer (`app/db/`), never raw SQL in routes or services.
- **Flask:** Routes return HTML only (Jinja2 templates). No `jsonify`. Use blueprints.
- **Frontend:** HTMX only. No JavaScript frameworks. No `static/js/` directory.
- **LLM:** Always use `app.llm.provider`; never call Ollama directly from routes.
- **Config:** User preferences in PostgreSQL; app config in YAML. No hardcoding.

## Commits

We use [Commitizen](https://commitizen-tools.github.io/commitizen/) and [Lefthook](https://github.com/evilmartians/lefthook) for conventional commits:

```bash
cz commit
```

Commit messages follow the format: `type(scope): description` (e.g. `feat(feed): add high-contrast toggle`).

## Quality Checks

Before submitting a PR:

```bash
ruff check .
ruff format --check .
mypy app/
pytest
```

Lefthook runs these on pre-commit and commit-msg.

## Pull Requests

1. Open an issue first for non-trivial changes.
2. Branch from `main`. Use a descriptive branch name (e.g. `fix/tts-fallback`, `feat/settings-page`).
3. Keep PRs focused. One concern per PR.
4. Ensure all tests pass and lint/format checks succeed.
5. Update documentation if behavior or config changes.

## Accessibility

Accessibility is a constraint, not a feature. Every UI change must:

- Maintain minimum 48×48px touch targets
- Preserve WCAG AA contrast (AAA in high-contrast mode)
- Avoid hover-only interactions and timed content
- Use semantic HTML
- Not break text-to-speech (Web Speech API)

When in doubt, favor clarity and usability over visual polish.

## Reporting Bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). Include:

- Steps to reproduce
- Expected vs actual behavior
- Environment (Docker, local, OS)
- Relevant logs or screenshots

## Suggesting Features

Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md). Explain the use case and how it aligns with the project’s goals: quality, clarity, and a clean reading experience for a general audience.

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## License

By contributing, you agree that your contributions will be licensed under the AGPL-3.0 license.
