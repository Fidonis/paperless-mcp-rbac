# Contributing to paperless-mcp-rbac

Thanks for considering a contribution to paperless-mcp-rbac! This document describes how to file issues, propose changes, and what is expected from contributors.

## Code of Conduct

Please follow common sense: be kind, assume good intent, and keep discussions focused on the project.

## Where to ask questions

- **General questions, ideas, brainstorming** → [GitHub Discussions](https://github.com/Fidonis/paperless-mcp-rbac/discussions)
- **Bugs, feature requests, documentation issues** → [GitHub Issues](https://github.com/Fidonis/paperless-mcp-rbac/issues), using the [issue templates](https://github.com/Fidonis/paperless-mcp-rbac/issues/new/choose)
- **Security vulnerabilities** → use [Private vulnerability reporting](https://github.com/Fidonis/paperless-mcp-rbac/security/advisories/new) instead of a public issue

## Reporting bugs and requesting features

We use GitHub Issue Forms. When you click *New issue*, you'll see these entry points:

- **Bug report** — for reproducible bugs
- **Feature request** — for new functionality or enhancements
- **Documentation** — for missing, wrong, or unclear docs
- **Question / Discussion** (link) — redirects to Discussions

Each form prefills the right labels and structure, so please use them rather than blank issues.

## Pull request workflow

1. Open or comment on the issue you intend to work on, so duplicate effort can be avoided.
2. Create a feature branch from `main`. Branch naming:
   - `feat/<short-name>` — new features
   - `fix/<short-name>` — bug fixes
   - `docs/<short-name>` — documentation
   - `refactor/<short-name>` — refactoring without behavior change
   - `test/<short-name>` — adding or fixing tests
   - `ci/<short-name>` — CI/CD changes
   - `chore/<short-name>` — maintenance
3. Make your change in small, reviewable commits.
4. Open a pull request against `main`. The PR template is filled in automatically; please complete each section, especially **Linked issues**, **Type of change**, and **Test plan**.
5. CI runs lint and PR-title checks. Address any failures. Once green, request a review.
6. PRs are merged via **Squash & Merge**. The PR title becomes the squash commit message — make sure it follows Conventional Commits (see below).

## Commit and PR title convention

We use [Conventional Commits](https://www.conventionalcommits.org/) for PR titles, which are squashed into the merge commit. This drives release notes (via release-drafter) and version bumps automatically.

Format: `<type>[(<scope>)][!]: <subject>`

| Type | Use for |
|---|---|
| `feat` | New user-facing feature (minor version bump) |
| `fix` | Bug fix (patch version bump) |
| `docs` | Documentation changes |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | Performance improvement |
| `style` | Formatting only, no code change |
| `test` | Adding or fixing tests |
| `ci` | CI configuration |
| `build` | Build system / dependencies |
| `chore` | Maintenance tasks |
| `revert` | Reverts a previous commit |

Examples:

- `feat: add upload_document MCP tool`
- `fix(auth): reject tokens with an unexpected audience`
- `docs: document NPM header-strip requirement`
- `feat!: drop support for Python 3.11`

A `!` after the type or scope marks a **breaking change** and triggers a major version bump.

The subject must be lowercase, in imperative mood (*"add"*, not *"added"* or *"adds"*), without a trailing period.

A CI check enforces this on PR titles.

## Code style

Linters run on every push and pull request:

- **Python** — [`ruff`](https://docs.astral.sh/ruff/) for linting and import ordering
- **YAML** — [`yamllint`](https://yamllint.readthedocs.io/)

Type checking with [`mypy`](https://mypy-lang.org/) (strict mode) is configured for the server in `src/pyproject.toml`; please run it locally before pushing.

Run the checks locally before pushing:

```bash
# YAML lint — from the repository root
yamllint .

# Python lint + type check — from src/
cd src
uv run ruff check .
uv run mypy .
```

Ruff configuration lives in `src/pyproject.toml`; the yamllint configuration is in `.yamllint`.

## Local development

See the [README](./README.md) for full setup. The short version:

```bash
cd src
uv sync                        # create src/.venv with dependencies
cp .env.example .env           # adjust as needed
uv run python main.py
```

The repository keeps the production server in `src/`. There is no virtual environment at the repository root.

## License

paperless-mcp-rbac is licensed under the MIT License.

---

Thanks again for contributing!
