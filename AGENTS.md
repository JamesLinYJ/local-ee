# Local EE engineering instructions

Read `docs/architecture.md` before changing architecture or adding a subsystem. This is an existing local research platform, not a blank starter. Preserve catalog versions, results, dependency locks and security boundaries. The user explicitly deleted the former VM and database; do not restore old account/job backups automatically.

## Scope and priorities

1. Read `GOAL.md` for the user's current priority: Python-first GEE API and computation-semantic compatibility, starting with measured probes and `docs/gee-python/list.md`, then completing actual workflows. Preserve the verified JavaScript, Python/openEO, map, export, administration and dataset paths. Track the full pinned API inventory and remaining differences. Modular administration, dataset lifecycle and self-hosted authentication remain part of the broader architecture; read `docs/admin-components.md` before integrating management components. For cloud continuation, also read `docs/cloud-handoff.md`; Linux tests do not establish macOS native acceptance.
2. Separate official-client syntax/serialization, supported local compilation, numerical correctness, and comparisons against GEE. Never claim all API signatures are implemented backend algorithms.
3. Keep local/offline operation and internal-only telemetry. Do not introduce external fonts, map/geocoding services, OAuth providers, analytics, ETL billing or error reporters by default.
4. Use modular interfaces; prefer a modular control plane and isolated executors over unneeded microservices. Keep compatibility facades during incremental refactors.

## Source ownership and structure

- `gee/api/`: routes, auth, typed input/output; delegate science and scheduling to services.
- `gee/services/`: use cases, permissions, quotas, persistent lifecycle.
- `gee/compat/earthengine/`: canonical pure EE DAG decoder, IR and compiler; no user-code execution or external fetches. `gee/ee_translate.py` is a 23-line backward-compatible import facade; add and change compiler behavior in the canonical package, then preserve the facade's public names.
- `runtimes/eejs/`: offline official SDK and isolated JS runner. Preserve vendor licenses and hash/version locks.
- `gee/ee_python_*.py`: pinned official Python SDK offline initialization, bounded loopback transport, local map/task/export adapters. Keep legacy EE serialization shared with the JS compiler, preserve openEO `connection`, and reject cloud authentication/discovery or unsupported export parameters. SDK method existence is not backend support.
- `gee/graph.py`: canonical process graph validation; every newly exposed process needs source review and focused validation.
- `gee/artifacts.py`: shared physical output boundary. All result readers and publication must use it.
- `web/src/components/`, `web/src/hooks/`, `web/src/lib/`: TypeScript + React functional components, hooks and typed protocol boundaries, no promotional/mission-statement copy. Use strict TypeScript; no Vue runtime or compatibility wrappers in the served frontend. Shared visual tokens and accessible controls; map/editor usable at common desktop widths.
- `deploy/`, `compose*.yaml`: explicit runtime and production profiles. `deploy/native-lock.json` and `.native/engine-lock.json` identify the current native deployment. Container image locks and old `audit/` evidence are historical.
- Check inherited `AGENTS.md` before editing vendor subtrees. Prefer adapters or minimal documented patches; never silently rewrite pinned upstream code.

## File size and cohesive modules

- Most first-party business modules should fit around 150–250 readable source lines. At roughly 300 lines, review whether the file mixes responsibilities; above 400 lines, normally separate cohesive concerns before adding more behavior. These are review guidelines, not hard limits or a reason to compress code.
- Separate request/state lifecycles from presentation, resource-specific administration from the shell, and map/graph engine integration from controls. Keep state ownership, effect dependencies, cleanup and public interfaces explicit; do not create many tiny forwarding files or generic abstractions merely to reduce line counts.
- Existing compiler guidance below is more specific. Generated code, pinned vendor code and data catalogues do not need mechanical splitting. A longer cohesive algorithm can remain intact when splitting would obscure its invariants.

## Earth Engine compiler modularity

- Keep compiler code separated by responsibility: decoding/catalog/filtering, grouped operation dispatch, IR and static/date values, graph/pixel/temporal compilation, and capability reporting. Extend the closest cohesive module; split only when a boundary improves ownership, review or reuse.
- Aim for modules around 200 source lines as a maintainability guideline, not a hard limit. Do not minify code or mechanically split files just to meet a line count; keep functions and types readable and their dependencies explicit.
- Keep new compiler-to-compiler imports within `gee.compat.earthengine`; do not add imports from the legacy `gee.ee_translate` facade or deepen transitional dependencies on root-level helper modules. Add or update focused semantic checks and the capability documentation when changing behavior.
- A module, handler or facade export is not proof of complete API or numerical support. New semantics, including `unmask` and new native-adapter behavior, remain unverified until their declared scope passes positive, negative, boundary and numerical validation. Preserve all existing resource limits and explicit rejection paths.

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

- The public source repository is `JamesLinYJ/local-ee`. The user prefers direct pushes; do not create pull requests unless requested. Protected `main` still requires successful GitHub Actions `python` and `frontend` checks on the exact commit, an up-to-date base and linear history, including for administrators. When checks have not run, push that commit to a temporary validation branch, wait for CI, then fast-forward `main` to the identical commit and remove the temporary branch. Never force-push or delete `main`, bypass checks, or temporarily disable protection to publish changes.
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
