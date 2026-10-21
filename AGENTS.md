# Local EE engineering instructions

Read `docs/architecture.md` before changing architecture or adding a subsystem. This is an existing local research platform, not a blank starter. Preserve catalog versions, results, dependency locks and security boundaries. The user explicitly deleted the former VM and database; do not restore old account/job backups automatically.

## Scope and priorities

1. Read `GOAL.md` for the user's current priority: advance toward complete GEE JavaScript API and computation-semantic compatibility through verifiable real-project slices. Track the full pinned API inventory and remaining differences; preserve the verified Python/openEO, map, export, administration and dataset paths. Modular administration, dataset lifecycle and self-hosted authentication remain part of the broader architecture; read `docs/admin-components.md` before integrating management components.
2. Separate official-client syntax/serialization, supported local compilation, numerical correctness, and comparisons against GEE. Never claim all API signatures are implemented backend algorithms.
3. Keep local/offline operation and internal-only telemetry. Do not introduce external fonts, map/geocoding services, OAuth providers, analytics, ETL billing or error reporters by default.
4. Use modular interfaces; prefer a modular control plane and isolated executors over unneeded microservices. Keep compatibility facades during incremental refactors.

## Source ownership and structure

- `gee/api/`: routes, auth, typed input/output; delegate science and scheduling to services.
- `gee/services/`: use cases, permissions, quotas, persistent lifecycle.
- `gee/compat/earthengine/` (initial implementation may be `gee/ee_translate.py`): pure EE DAG decoder/IR/compiler; no code execution or external fetches.
- `runtimes/eejs/`: offline official SDK and isolated JS runner. Preserve vendor licenses and hash/version locks.
- `gee/graph.py`: canonical process graph validation; every newly exposed process needs source review and focused validation.
- `gee/artifacts.py`: shared physical output boundary. All result readers and publication must use it.
- `web/src/components/`, `web/src/hooks/`, `web/src/lib/`: TypeScript + React functional components, hooks and typed protocol boundaries, no promotional/mission-statement copy. Use strict TypeScript; no Vue runtime or compatibility wrappers in the served frontend. Shared visual tokens and accessible controls; map/editor usable at common desktop widths.
- `deploy/`, `compose*.yaml`: explicit runtime and production profiles. `deploy/native-lock.json` and `.native/engine-lock.json` identify the current native deployment. Container image locks and old `audit/` evidence are historical.
- Check inherited `AGENTS.md` before editing vendor subtrees. Prefer adapters or minimal documented patches; never silently rewrite pinned upstream code.

## Security and persistence invariants

- User JS/Python must execute in separate native macOS Seatbelt processes via sandbox-exec, never in the API process. Default-deny filesystem/network policy, dedicated scratch/output paths, scrubbed environment and bounded CPU time/RSS/process count/wall time/logs are mandatory. Refuse execution if the sandbox is unavailable. Never fall back to unconfined subprocesses, VMs or containers. Scripts have only their short-lived API token; no DB/provider credentials or other users' files.
- Batch networking permits only Spark/Py4J loopback IPC. Ingestion permits no networking. Scripts may connect only to the configured loopback API port. Preserve graph limits/URL/UDF/namespace rejection. Never broaden outbound access to fix a native dependency; use an explicit adapter and a legitimate/negative control.
- A script token is short lived and bound to its user, scope and parent job. Scope is checked server-side; never trust user-supplied user IDs, role claims, paths, job status, layer intents or asset lists.
- All result directory components and files are physical, inside the owning job, and not symlinks; file names are immediate regular children. Reuse the central resolver.
- Provider ingestion uses allowlists, expected drivers, finite bytes/pages/deadlines/decoded sizes, real destination filesystem checks, low privileges and restricted mounts/DB role.
- All schema changes use additive, recoverable migrations; do not delete or rewrite existing user research artifacts. Back up before production migrations and preserve secret permissions0600.
- Do not log tokens/passwords or print `.env`/login credentials. Existing deployment secrets stay outside build contexts and images.
- Do not remove vulnerable class metadata or suppress findings to manufacture clean scans. Record real fixes, mitigations, residual risk and coverage limits.

## Scientific compatibility

- Preserve half-open millisecond dates; distinguish filterBounds selection from clip masking.
- Preserve band order/names, collection ordering, grid/CRS, scale/offset, units, masks and NoData. Verify median and ordered mosaic independently with more than one input.
- GEE normalizedDifference has negative-input mask and naming/property rules; expression ND is different. GEE updateMask and openEO mask have opposite boolean meaning.
- Data aliases state coverage, missing bands and preprocessing. Never fabricate QA60, substitute SCL silently, restore already-masked pixels by assertion, or present the local preprocessed sample as a full GEE dataset mirror.
- Reject unsupported operations/parameters explicitly with stable errors. Never silently drop scale/crs/masks, replace a reducer with a different algorithm, or use dummy data as successful computation.

## Verification and workflow

- The public source repository is `JamesLinYJ/local-ee`. Submit changes through pull requests. Protected `main` requires the GitHub Actions `python` and `frontend` checks, an up-to-date base, resolved conversations and linear history; force pushes and branch deletion are disallowed, including for administrators. Do not disable protection to publish changes. With only one maintainer, approving reviews are not required; revisit when another trusted maintainer joins.
- Inspect code and direct callers first. Keep bounded changes and ownership clear; parallel workers must not edit overlapping files and must report evidence/limits.
- Use existing package managers/locks. Keep builds in temporary output directories, then safely deploy static assets. No public hosting or publishing for this local platform without user authorization.
- Run syntax/build checks, focused negative/semantic tests, and legitimate end-to-end controls appropriate to the changed module. Test real UI routes when the behavior is user-visible.
- For EE, include date boundaries, distinct multi-scene reductions, negative ND, mask direction, select/rename/addBands and missing bands; independent numerical references are required for supported scientific claims.
- Preserve prior evidence. Harnesses use a new `GEE_AUDIT_DIR`; never overwrite historical audit files. Distinguish a regenerated report from original evidence.
- Clean task-created build scratch, completed-task caches and duplicate test downloads after verification. Retain concise reports, failure records and required reproducible fixtures; keep runtime dependencies, user data and formal outputs. Check that no task is using a path before removing it, and record meaningful cleanup.
- Deploy only checked native dependencies/code, record versions/hashes, then read back process identity, architecture and user-visible behavior. Do not treat a successful build as running acceptance.
- Report changes, exact verified scope, meaningful failures and unresolved work. Do not mark the active goal complete until its required slices are actually done.

## Environment

Project root: this directory. Host is Apple Silicon macOS. **Do not use or recreate Docker, Colima, containers or virtual machines.** The dedicated Colima profile, its images and database were deleted at the user's request. Windows VM is unrelated and must remain untouched. Use `.venv/bin/python scripts/native.py start|stop|status`; native PostgreSQL is private to `.native/postgres` and uses a Unix socket only. Current URL: http://localhost:8787. Fresh admin credentials: `deploy/native-login.txt` (0600); never print them. Large retained assets remain in `data/`; old results remain files but are not automatically reassigned to the new account. Scratch work stays in the parent `work/`, user-facing deliverables in this `outputs/` tree. Read `docs/native-macos.md` before changing execution or service lifecycle.
