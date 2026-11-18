# Branch protection and secret scanning (steps G.6 and O1.8)

Applies to both repositories: `maximusntibrey/eqp4l-backend` and `maximusntibrey/p4linventory-frontend`, branches `main` and `develop` (TASKS 1.3, 1.6 G.6; DevOps s4, s8).

**Status: prepared, not applied.** Requiring the `check` status before CI has run once would block merging the Phase A pull requests that add CI. Apply these commands only after:

1. the Phase A pull requests are merged into `develop` in both repos, and
2. the `CI / check` job has reported at least once in each repo (so GitHub knows the `check` context).

Tracked as OQ-5 in `TASKS.md`. G.1, G.2 ("protect `main`") and G.6 are ticked only after the commands below have been run and the verification output has been checked.

## What the rules enforce

| Requirement (TASKS G.6, DevOps s4) | Setting |
|---|---|
| Pull request required, no direct commits | `required_pull_request_reviews` present, so every change must arrive by pull request |
| No approving review required | `required_approving_review_count: 0`. There is one GitHub account and the author cannot approve their own PR. Reviewer approval is recorded as a PR comment |
| CI green required | `required_status_checks.checks: [{"context": "check"}]` (the job name in `.github/workflows/ci.yml`), `strict: true` (branch must be up to date with its base) |
| Rules apply to the owner too | `enforce_admins: true` |
| No force pushes | `allow_force_pushes: false` |
| No branch deletion | `allow_deletions: false` |
| Review comments resolved before merge | `required_conversation_resolution: true` |

Sprint and feature branches are not protected: feature pull requests merge into the sprint branch, and the local pre-commit hook `no-commit-to-branch` already blocks direct commits to `main`, `develop` and `sprint/*`.

## Commands (Git Bash)

`gh` is not on the Git Bash PATH on this machine, so the full path is used.

```bash
GH="/c/Program Files/GitHub CLI/gh.exe"

for repo in eqp4l-backend p4linventory-frontend; do
  for branch in main develop; do
    echo "== $repo $branch"
    "$GH" api --method PUT \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "repos/maximusntibrey/$repo/branches/$branch/protection" \
      --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "checks": [{ "context": "check" }]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
  done
done
```

## Verification (run after applying, paste the real output in the PR or report)

```bash
GH="/c/Program Files/GitHub CLI/gh.exe"

for repo in eqp4l-backend p4linventory-frontend; do
  for branch in main develop; do
    echo "== $repo $branch"
    "$GH" api "repos/maximusntibrey/$repo/branches/$branch/protection" --jq '{
      checks: [.required_status_checks.checks[].context],
      strict: .required_status_checks.strict,
      pr_required: (.required_pull_request_reviews != null),
      approvals: .required_pull_request_reviews.required_approving_review_count,
      enforce_admins: .enforce_admins.enabled,
      force_pushes: .allow_force_pushes.enabled,
      deletions: .allow_deletions.enabled
    }'
  done
done
```

Expected for each of the four branches: `checks: ["check"]`, `strict: true`, `pr_required: true`, `approvals: 0`, `enforce_admins: true`, `force_pushes: false`, `deletions: false`.

A practical test once protection is on: `git push origin develop` from a local commit must be rejected with `protected branch hook declined`. Do not try a force push to test it.

## Secret scanning (O1.8)

Checked on 2026-11-18 (read-only `gh api repos/maximusntibrey/<repo> --jq .security_and_analysis`): both repositories are public and already have `secret_scanning: enabled` and `secret_scanning_push_protection: enabled`. No change is needed. Re-check with:

```bash
GH="/c/Program Files/GitHub CLI/gh.exe"
for repo in eqp4l-backend p4linventory-frontend; do
  "$GH" api "repos/maximusntibrey/$repo" --jq '{repo: .name, secret_scanning: .security_and_analysis.secret_scanning.status, push_protection: .security_and_analysis.secret_scanning_push_protection.status}'
done
```

If either ever shows `disabled`, enable it with:

```bash
"$GH" api --method PATCH "repos/maximusntibrey/<repo>" --input - <<'JSON'
{ "security_and_analysis": {
    "secret_scanning": { "status": "enabled" },
    "secret_scanning_push_protection": { "status": "enabled" } } }
JSON
```

Locally, the gitleaks pre-commit hook blocks staged secrets (T.3), and CI scans the full history with gitleaks on every pull request (G.5).

## Optional (owner or orchestrator decision, not part of G.6)

TASKS 1.4 says "Delete merged feature branches". GitHub can do this automatically on merge (repository setting, not branch protection):

```bash
"$GH" api --method PATCH "repos/maximusntibrey/<repo>" -F delete_branch_on_merge=true
```

It is currently `false` in both repos. Note that it would also delete a sprint branch when the sprint-to-`develop` pull request merges, which matches the sprint routine in TASKS 1.5.
