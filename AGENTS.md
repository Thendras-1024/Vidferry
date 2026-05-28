# AGENTS.md

## Project Focus

Vidferry is a local-first video lead, download, processing, material, account, and publishing workflow.

Prioritize the current Web workflow and the main `sau` CLI path. Do not expand legacy `examples/` unless a task explicitly asks for it.

## Code Modularization Rules
Split code by functional modules. Do not put all functions and logic into one single file. Create separate files for business features, utilities and configurations. The entry file is only for invocation, without specific business logic.

## State Rules

- Material deletion must update the related video lead.
- Lead deletion must block when processed video or active jobs exist.
- Active jobs are `queued` or `running`.
- Interrupted jobs must become `abnormal` with an error code and reason.
- Frontend must not directly fake completed download, process, or publish states.
- Do not add fallback logic to hide or bypass bugs unless the user explicitly approves that fallback. Prefer surfacing clear errors, logs, and root causes.

## Security Rules

- Never commit local secrets or artifacts: `.env`, `conf.py`, `cookiesFile/`, `db/*.db`, `qrcode.png`, `videos/`, `videoFile/`, `dist/`, `node_modules/`.
- Cookie, account, publish, delete, upload, and download endpoints are high-risk.
- Validate paths with `Path.resolve()` and keep them inside explicit allowed roots.
- Do not trust client-provided account names, file paths, publish files, or status values.

## Frontend Rules

- Use Vue 3 + Vite + Element Plus + Pinia.
- Do not add another UI framework.
- Keep the current light, compact operations-console style.
- Frontend actions should call backend APIs and reflect returned state.
- Do not run `npm run build` or `npm run dev` automatically. After frontend changes, tell the user and let the user restart/run the frontend.

## Validation

- Backend: `python -m py_compile sau_backend.py`
- Frontend: ask the user to run `cd sau_frontend && npm run dev`; do not run it automatically.
- For state changes, test lead deletion, material deletion, active-job locks, interrupted jobs, and missing-file recovery.

## Git Hygiene

- Do not revert unrelated user changes.
- Do not commit generated media, cookies, QR codes, local DBs, or build output.
- Keep dependency files readable text, especially `requirements.txt`.
