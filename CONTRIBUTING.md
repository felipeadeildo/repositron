# Contributing

Thanks for working on repositron. This is a small, dependency-light library;
the bar is "typed, tested, and boring to read". This file covers the tooling,
the conventions, and how a release happens.

## Toolchain

Everything runs through [uv](https://docs.astral.sh/uv/). One command sets up a
working environment with all dev tools:

```bash
uv sync
```

That installs the runtime dependency (`sqlalchemy`) plus the `dev` group:

| Tool | What it does |
|---|---|
| [ruff](https://docs.astral.sh/ruff/) | Linter and formatter (one tool for both) |
| [ty](https://github.com/astral-sh/ty) | Type checker |
| [prek](https://github.com/j178/prek) | Runs the pre-commit hooks (a faster `pre-commit`) |
| [zensical](https://github.com/zensical/zensical) | Docs build |

Run a command inside the environment with `uv run`, e.g. `uv run ruff check`.

## Pre-commit hooks

Hooks are defined in [`prek.toml`](prek.toml) and run `ruff` (check + format)
and `ty` on every commit. Install them once:

```bash
uv run prek install
```

After that, every `git commit` auto-fixes lint, reformats, and type-checks the
staged files. To run the hooks across the whole repo on demand:

```bash
uv run prek run --all-files
```

If a hook modifies files, the commit is aborted — restage (`git add`) and commit
again. Don't bypass hooks (`--no-verify`) to land code; fix the finding instead.

## Checks before you push

The hooks cover the common case, but run the full set yourself before opening a
PR:

```bash
uv run ruff check          # lint
uv run ruff format --check # formatting
uv run ty check            # types
uv run pytest              # tests
```

These are exactly what CI runs ([`.github/workflows/test.yml`](.github/workflows/test.yml))
on every push and PR.

The ruff config lives in `[tool.ruff]` in `pyproject.toml` (line length 100,
target `py313`). The lint set is intentionally broad — pyflakes, pyupgrade,
isort, bugbear, naming (`N`), annotations (`ANN`), and docstrings (`D`) — so
expect ruff to enforce more than the defaults. Keep the diff to ruff's
formatting; don't hand-format.

## Code conventions

- **Types are not optional.** Every public method is fully typed off the generic
  parameters — that's the whole point of the library. New code keeps it that
  way; `ty check` must pass with no ignores. If you genuinely need an escape
  hatch, scope it as narrowly as possible and leave a comment saying why.
- **Python 3.13+.** Use modern syntax: PEP 695 generics (`class Foo[T]:`),
  `type X = ...` aliases, `X | None` unions. No `typing.TypeVar`,
  `Optional`, or `Union`.
- **Line length** is 100. When a line genuinely can't be split (a long
  single-string docstring), `# noqa: E501` on that line is acceptable — used
  sparingly, as in `sql.py`.

### Docstrings

The `D` (pydocstyle) rules enforce these — let `ruff check --fix` shape them,
and match the existing style in `base.py` and `sql.py` before writing.

- **Multi-line docstrings** open with `"""` on its own line and the summary on
  the next line (the `D213` style — ruff will reformat to this):

  ```python
  """
  Read-only side of the repository contract.

  Longer explanation here, when the behaviour is subtle.
  """
  ```

- **One-line docstrings** stay on one line: `"""Get a single record by primary key, or None if absent."""`.
- **Public methods need a docstring.** Dunders (`__repr__`, `__bool__`, …) and
  argument-by-argument descriptions are exempt (`D102`/`D105`/`D417` ignored) —
  document the *why* and the edge cases, not each parameter or the type
  (the annotations already say it).
- **Documented attributes**: a bare string *below* the attribute, not a comment:

  ```python
  total: int
  """Total matching rows ignoring offset/limit; for computing page counts."""
  ```

## Tests

Tests live in `tests/`, run on in-memory SQLite, and need no setup beyond
`uv sync`. The pydantic-hydration test is skipped unless pydantic is installed,
so run with the extra to cover it:

```bash
uv run pytest                  # the suite
uv run --all-extras pytest     # also exercises the pydantic DTO path
```

Files split by behavior, not by method: `test_hydration.py`, `test_projection.py`,
`test_write.py`, `test_filtering.py`, `test_wiring.py`. Fixtures (engine, session,
test models, DTOs, payloads) live in `tests/conftest.py`. Add tests for new
behavior, not for every function; one assertion-rich test per behavior beats a
test per getter. Test files are exempt from the `D`/`ANN` lint rules.

## Commits

Use short, conventional-commit-style messages: `type: summary` on one line
(`feat:`, `fix:`, `docs:`, `ci:`, `chore:`, `refactor:`). Keep them to a single
line; let the diff speak.

## Releasing

Releases are published to [PyPI](https://pypi.org/project/repositron/) by
[`.github/workflows/release.yml`](.github/workflows/release.yml), triggered by
pushing a `v*` tag. Publishing uses PyPI **trusted publishing** (OIDC) — there's
no token to manage.

The version lives statically in `pyproject.toml` (`project.version`). Bumping it
is a manual, deliberate step. To cut a release:

```bash
# 1. Bump the version (patch | minor | major). This edits pyproject.toml.
uv version --bump patch

# 2. Commit the bump.
git commit -am "release: v$(uv version --short)"

# 3. Tag it and push. The tag is what triggers the publish.
VERSION=$(uv version --short)
git tag "v$VERSION"
git push origin main "v$VERSION"
```

Pushing the tag runs the workflow, which:

1. builds the wheel and sdist (`uv build`),
2. publishes them to PyPI (`uv publish`, via OIDC),
3. creates a GitHub Release with auto-generated notes and the built artifacts
   attached.

Versioning is [SemVer](https://semver.org/): `patch` for fixes, `minor` for
backwards-compatible features, `major` for breaking changes.

### One-time setup (already done for this repo)

For reference, trusted publishing requires:

- a GitHub environment named `pypi` (Settings → Environments), and
- a PyPI trusted publisher pointing at this repo, workflow `release.yml`,
  environment `pypi` (PyPI project → Publishing).

### If a release fails

A PyPI version is immutable — you can't republish the same version. If the
workflow fails *before* the publish step (e.g. a bad action pin), fix it, delete
and recreate the tag on the corrected commit:

```bash
git push origin :refs/tags/vX.Y.Z   # delete remote tag
git tag -d vX.Y.Z                   # delete local tag
git tag vX.Y.Z                      # recreate on the fixed HEAD
git push origin vX.Y.Z
```

If it failed *after* publishing to PyPI, bump to the next patch version instead.
