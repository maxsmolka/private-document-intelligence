# Repository and release security

This document records the security controls for the public PDI source repository and its release infrastructure. It does not replace the application threat model in [SECURITY.md](SECURITY.md).

## Trust and privacy boundary

GitHub source, issues, pull requests, reviews, Actions logs, release metadata, and container metadata are public. They must never contain private documents, extracted/OCR text, personal data, credentials, tokens, backups, exports, production logs, private hostnames or addresses, storage paths, or deployment topology. Public examples and fixtures must be synthetic or fully redacted. Suspected vulnerabilities belong in GitHub private vulnerability reporting, not a public issue.

## Default branch controls

`main` is protected by an active repository ruleset. Changes require a pull request and the stable `backend` and `frontend` CI checks. Required approvals are intentionally zero because this is currently a single-maintainer repository; requiring another reviewer would create a lockout rather than meaningful review. Force pushes and branch deletion are blocked. The repository administrator retains a narrowly scoped emergency bypass and can edit or disable the ruleset if GitHub or a broken check makes normal recovery impossible. Every bypass should be exceptional, documented, and followed by restoration of the rule.

Squash merge is the supported merge strategy. Head branches are deleted after merge. Merge commits and rebase merges are disabled to keep the public history and rollback boundary predictable.

## Release and tag controls

The active release-tag ruleset applies to `v*` tags. Existing release tags cannot be updated or deleted through ordinary Git operations; future version-tag creation remains possible. The repository administrator retains emergency recovery through ruleset administration. Published release tags and versioned GHCR images are immutable release records: never move a tag, rebuild an existing version, or overwrite an existing versioned image.

The release workflow runs only for `v*` tag pushes. Quality jobs run before publication. The publishing job alone receives `contents: write` and `packages: write`; other jobs and the repository default token are read-only. Checkout credentials are not persisted. Third-party actions are pinned to full commit SHAs, and Dependabot maintains action references through normal reviewable pull requests.

The backend and web images are public for anonymous pulls. Only the release workflow's repository-scoped `GITHUB_TOKEN` is used to publish; no long-lived registry credential is stored in repository Actions secrets. Images include BuildKit SBOM and provenance attestations. Future signing or stronger attestations should use a new release version and a documented keyless or hardware-backed trust model; never retrofit or republish v1.0.0.

## Automated security controls

- Secret scanning and push protection are enabled.
- Dependabot vulnerability alerts and security updates are enabled. Version-update pull requests remain review-only; there is no automatic merge.
- Private vulnerability reporting is enabled and linked from the public issue chooser.
- CodeQL default setup scans Python and JavaScript/TypeScript. It is observed before becoming a required merge check so a platform or configuration issue cannot lock the sole maintainer out.
- GitHub Actions tokens default to read-only, cannot approve pull requests, and workflows declare the permissions they need.
- Workflow actions must use full commit SHAs. Pull-request workflows do not use `pull_request_target`, expose secrets, or evaluate contributor-controlled text as shell code.

Native secret scanning is the primary committed-secret control. A second secret scanner is not added merely for duplication: another privileged third-party Action would increase supply-chain and maintenance surface. Reconsider defense-in-depth scanning if native coverage, repository visibility, or compliance requirements change.

## Recovery procedure

If a required check is unavailable or a ruleset prevents a necessary repair:

1. Confirm the problem is repository infrastructure, not a failing product check.
2. Record the affected rule, check, commit, and reason without including secrets or private infrastructure data.
3. As repository administrator, temporarily narrow or disable only the blocking rule. Do not enable force pushes or tag rewriting unless recovering from a confirmed repository compromise.
4. Apply the smallest repair through a pull request whenever GitHub permits it.
5. Restore the rule immediately, verify `main` CI, and re-check release tags and versioned image digests.

If the owner account or token is unavailable, use GitHub account recovery. There is intentionally no alternate deploy key, long-lived package token, webhook, or automation principal with broad repository write access.

## Controls intentionally deferred

- CodeQL is not a required check until repeated default-branch and pull-request runs prove its exact check names and stability.
- Commit signing and keyless release signing require a separately designed trust and recovery process. Existing v1.0.0 artifacts remain untouched.
- Generic non-provider secret patterns and secret validity checks remain subject to GitHub plan/capability and false-positive evaluation; provider secret scanning and push protection remain enforced.
- GHCR administrative access is not broadened to add redundant publishers. Anonymous pull access and release-workflow publication are verified independently.

Review this document whenever maintainership, repository visibility, GitHub plan, release tooling, or package publishing changes.
