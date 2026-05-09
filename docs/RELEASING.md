# Release process

## Branch model

- **`main`** — trunk. Every commit lands here. Users on `--dev` follow it.
- **Tags `vX.Y.Z[bN]`** — release milestones. Default users follow the latest one.
- No long-lived `develop` or `release/*` branches. Use feature branches if a
  change is risky and you want a PR to review yourself.

## Versioning

Semantic Versioning, with `bN` suffix for betas:

- `0.1.0b1`, `0.1.0b2`, `0.1.0b3`, … → public testing
- `0.1.0` → first stable
- `0.1.1` → patch (bug fix only)
- `0.2.0` → minor (new features, backward-compatible)
- `1.0.0` → first non-beta major

The `pyproject.toml` `version` field uses PEP 440 syntax (`0.1.0b1`,
`0.1.0`, …). Tags are `v` + that string (`v0.1.0b1`, `v0.1.0`).

## Cutting a release

1. **Smoke-test on `main`**. Run the TUI, do a sync, restart, plug a known
   USB. Anything broken? Fix it first, commit, repeat.

2. **Bump the version** in `pyproject.toml`:

   ```toml
   version = "0.1.0b2"
   ```

   Commit:

   ```bash
   git commit -am "release: 0.1.0b2"
   ```

3. **Tag and push**:

   ```bash
   git tag v0.1.0b2
   git push origin main --tags
   ```

4. **GitHub Actions takes over** (`.github/workflows/release.yml`):
   - Creates a Release at `https://github.com/cinhil/mixtape/releases/tag/v0.1.0b2`
   - Auto-generates notes from the commits since the previous tag
   - Marks it as *Pre-release* if the tag contains `alpha`/`beta`/`rc`/`bN`/`aN`

5. **Done.** Users running the install one-liner will pick up the new
   version on their next re-run.

## How users follow versions

The default install one-liner targets the **latest GitHub Release tag**
(stable channel). Users who want to track `main` pass `--dev`:

```bash
# Stable (default)
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash

# Dev / cutting edge (follows main)
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --dev

# Pin to a specific version
curl -fsSL https://raw.githubusercontent.com/cinhil/mixtape/main/install.sh | bash -s -- --ref=v0.1.0b1
```

(PowerShell users use `-Dev` / `-Ref X` flags instead — same logic.)

## What if I need to fix a bug on a released version?

For a beta project, just push the fix to `main`, bump version, tag, push.
End-users on `stable` get it within their next re-run window.

For a stable release with users in production who can't re-test, you'd
create a `release/0.1.x` branch from the tag, cherry-pick the fix, and tag
`v0.1.1`. Out of scope while we're in beta.

## Releasing checklist (copy-paste)

```bash
# 1. Smoke test
./run.sh
# 2. Bump
$EDITOR pyproject.toml          # version = "0.1.0bN"
git commit -am "release: 0.1.0bN"
# 3. Tag + push
git tag v0.1.0bN
git push origin main --tags
# 4. Verify the workflow ran:
#    https://github.com/cinhil/mixtape/actions
# 5. Verify the release page:
#    https://github.com/cinhil/mixtape/releases
```
