<!--
Thanks for contributing to zuke-python! A few things that make review fast:

The PR title IS the release trigger. This repo squash-merges, and
release-please parses only the squashed subject (your PR title). Title this PR
as a Conventional Commit so the right version is cut:

  feat: add the service builder             -> minor bump
  fix: honour the worker's cwd in exec      -> patch bump
  docs|chore|refactor|test: ...             -> no release
-->

## What & why

<!-- What does this change do, and what problem does it solve? Explain the
motivation, not just the mechanics. -->

## Related issues

<!-- Required: "Closes #123". Every change starts with an issue — file one from
.github/ISSUE_TEMPLATE (feature request, bug report, or chore) before opening
this PR. See AGENTS.md. -->

## Checklist

- [ ] This PR closes a tracking issue (`Closes #<n>` above).
- [ ] The PR title is a
      [Conventional Commit](https://www.conventionalcommits.org/)
      (`type(scope): summary`).
- [ ] `uv run poe ci` passes locally (format, lint, type-check, tests).
- [ ] Tests were added or updated; coverage stays at 95%+ (lines and branches).
- [ ] Docs updated in the same PR (`README.md`, docstrings) when behaviour
      changed.
- [ ] No `Any`, no `cast`, no `type: ignore` in `src/` (narrow with guards
      instead).
- [ ] No dead code: unreachable branches and can't-fire fallbacks are removed,
      with types tightened so the impossible state is unrepresentable.
- [ ] No duplicated logic: an existing helper is imported rather than retyped.
- [ ] A protocol change was made in the engine repository first, and this PR
      pins the engine version that carries it.
- [ ] The code is written using AI assisted coding.

<!-- Keep illustrative code in this description, not in commit message bodies:
release-please's strict parser can drop a commit whose body contains code with
parentheses, silently skipping it from the release. -->
