# Dependency audit — 1.3.1

Audited 2026-11-09 UTC against first-party release APIs and action manifests. Baseline: `dev` at `5f897ae` (integration 1.3.0). No package installation, commit, push, release, or deployment is part of this audit.

## CI actions

| Workflow dependency | Current reference | Latest published release observed | Decision and manifest evidence |
| --- | --- | --- | --- |
| `actions/checkout` | `v7` | [v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1), 2026-07-20 | Already on current major; retain moving alias. [Manifest](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml) uses `node24`. No custom inputs in this repository. |
| `actions/setup-python` | `v7` | [v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0), 2026-10-22 | Already on current major; retain moving alias. [Manifest](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/action.yml) uses `node24` and accepts `python-version`. New mirror inputs are optional and unused. |
| `hacs/action` | `main` | [22.5.0](https://github.com/hacs/action/releases/tag/22.5.0), 2022-05-28 | Retain maintained branch, not an old release. [Manifest](https://github.com/hacs/action/blob/1ebf01c408f29afcb6406bd431bc98fd8cbb15aa/action.yml) is a Docker action using `docker://ghcr.io/hacs/action:main`; required `category: integration` is supplied. |
| `home-assistant/actions/hassfest` | `master` | Repository [1.0.0](https://github.com/home-assistant/actions/releases/tag/1.0.0), 2020-04-16 | Retain [documented upstream reference](https://github.com/home-assistant/actions/blob/86d4564712fa02543c808e3a693dd04f9d3f8361/README.md). [Manifest](https://github.com/home-assistant/actions/blob/86d4564712fa02543c808e3a693dd04f9d3f8361/hassfest/action.yml) is composite and invokes Docker image `ghcr.io/home-assistant/hassfest` (implicit `latest`), not a Node action. |

Release discovery used `https://api.github.com/repos/{owner}/{repo}/releases/latest` for each repository above; manifest links freeze the actual observed ref commits. Moving aliases/branches and the validation images remain upstream-controlled rather than reproducibly pinned. Patch/minor releases within `v7` do not require textual version changes. No supported action upgrade was outstanding; only the Python matrix's stale HA-version comment was corrected.

Both Node 24 actions require runner **v2.327.1 or newer**, per their [checkout](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/README.md) and [setup-python](https://github.com/actions/setup-python/blob/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0/README.md) documentation. Checkout documents **v2.329.0 or newer** for authenticated Git commands inside Docker container actions. These workflows use GitHub-hosted `ubuntu-latest`, not a declared self-hosted runner. HACS/Hassfest additionally require Linux/Docker; a static manifest audit does not verify hosted image execution.

## Home Assistant owns runtime dependencies

`hacs.json` declares HA **2024.1.0** minimum; `custom_components/pymc_repeater/manifest.json` has `requirements: []`. There is no standalone requirements/lockfile, package manifest, Dockerfile, or third-party installation step. Do not add pip pins or a pip Dependabot ecosystem for packages supplied by HA.

| Upstream HA release | Python requirement | Relevant HA-owned dependency pins |
| --- | --- | --- |
| [2024.1.0 pyproject](https://github.com/home-assistant/core/blob/2024.1.0/pyproject.toml) — declared minimum | `>=3.11.0` | `aiohttp==3.9.1`, `yarl==1.9.4`, `voluptuous==0.13.1` |
| [2026.11.0 pyproject](https://github.com/home-assistant/core/blob/2026.11.0/pyproject.toml) — stable observed via [latest release API](https://api.github.com/repos/home-assistant/core/releases/latest), published 2026-11-04 | `>=3.14.2` | `aiohttp==3.14.5`, `yarl==1.25.1`, `probatio==0.13.0` |

HA 2026.11.0's [initialization](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/__init__.py) calls `probatio.compat.install_as_voluptuous()` before integration imports. Its lack of a direct `voluptuous` pin is not evidence that the integration needs one. Preserve HA's dependency resolution and compatibility alias. These are observed HA pins, not recommendations to backport modern package versions to old HA. Minimum-version metadata and upstream source inspection do not establish that every integration API works on that minimum; actual runtime compatibility remains untested here.

## Dependabot

Retain `.github/dependabot.yml` unchanged: GitHub Actions, directory `/`, weekly Monday **08:00 America/New_York**, `target-branch: dev`, five open PRs, existing labels and commit-message policy. No missing ecosystem or unnecessary grouping/ignore rule was found.

[GitHub's configuration documentation](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file) governs this policy: scheduled configuration is read from default `main`; `target-branch` directs version-update PRs to `dev`, not security-update behavior away from the default branch. The existing configuration is already present in the locally tracked `origin/main`; a remote `ls-remote --symref` confirmed `main` as default at `5f897aea7050cb022c05c4e9406eade611c6bd4e`. No remote configuration or bot run was changed or triggered.

## Verification and boundaries

- All three workflows passed **actionlint 1.7.12** with optional shellcheck/pyflakes disabled. The official Linux archive was verified against its published SHA-256 (`8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`); the tool was kept outside the checkout.
- Python Smoke's 3.11–3.14 matrix runs JSON parsing, compilation, and standard-library contract tests, **not four installed Home Assistant environments**. The `3.14` selector is a Python minor selector, not an exact HA runtime pin.
- YAML parsing and whitespace checks validate repository structure, not GitHub runner provisioning, container image pulls, HACS/Hassfest execution, or actual Dependabot PR creation.
- No HA runtime installation, live integration loading, entity/service-schema compatibility, authenticated Repeater HTTP, or hardware/RF behavior was exercised by this dependency audit. Hosted checks and runtime verification remain separate release gates; no action-only check proves them.
