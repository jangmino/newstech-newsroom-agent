# AGENTS.md

## Mission

Build a reliable workshop application that helps newsroom professionals understand the difference between a general chatbot answer and a source-constrained, auditable public-data workflow.

The product is not an autonomous article writer. It produces a reviewable briefing and stops at human verification.

## Read first

Before changing code, read these files in order:

1. `docs/PRODUCT_BRIEF.md`
2. `docs/ARCHITECTURE.md`
3. `docs/CODEX_HARNESS.md`
4. The relevant file under `docs/decisions/`

Use `git status --short` before edits. Preserve user changes and do not overwrite unrelated work.

## Current phase

- Phase: M3 event readiness; M1 and constrained M2 flows are complete.
- Live Gemini, OpenDART, and KOSIS calls are off by default.
- Preserve the mock flow and explicit approval before live data access, including cache reuse.
- Do not deploy or enable billing unless the user explicitly asks.

## Architecture constraints

- `apps/web`: React + TypeScript + Vite.
- `apps/api`: Python 3.12 + FastAPI.
- Local development uses two processes.
- Staging uses one Cloud Run container: build the web app, then serve its static output from FastAPI.
- Keep one orchestrating agent with tools. Do not introduce a multi-agent framework without a recorded decision.
- LLMs interpret questions and compose explanations. Deterministic code performs arithmetic, ranking, validation, and normalization.
- External APIs are accessed only by the backend.
- Keep provider-specific code behind adapters in `apps/api/src/newsroom_agent/providers/`.
- Keep frontend types aligned with backend response contracts.

## Product rules

- Use Korean for participant-facing text.
- Always show the selected source, interpreted conditions, unit, retrieval time, formula, and caveats.
- If a question is ambiguous, request clarification instead of silently choosing consequential assumptions.
- Never present generated output as verified journalism.
- Preserve a visible human-review status.
- Do not add article auto-publication, CMS integration, or arbitrary web search within the MVP.
- A live-provider failure must return a clear error or a labeled snapshot fallback; never fabricate live data.

## Security and credentials

- Never commit `.env`, API keys, service-account JSON, access codes, or copied production responses containing secrets.
- Never expose Gemini, OpenDART, or KOSIS keys in frontend code or `VITE_*` variables.
- Local development may use the developer's personal credentials only in `.env`.
- Stage and event environments must use credentials, billing, and GCP resources owned by Konkuk University or the organizer.
- Use Secret Manager for stage/event secrets.
- Do not log secrets, authorization headers, full access codes, or raw credential-bearing URLs.
- Live external calls in automated tests are forbidden. Use fixtures and mocked transports.

## Commands

Run from the repository root unless noted otherwise.

```bash
make doctor       # tool and configuration check
make dev-api      # FastAPI at :8000
make dev-web      # Vite at :5173
make test         # backend tests
make test-web     # frontend behavior tests with mocked responses
make typecheck    # frontend TypeScript check
make build        # frontend and backend package checks
make check        # all local validation
```

## Change workflow

1. Restate the bounded user-visible outcome.
2. Inspect the minimum relevant files.
3. Make the smallest coherent change.
4. Add or update tests for behavior and data contracts.
5. Run the narrowest relevant check, then `make check` for a completed slice.
6. Update docs when commands, contracts, environment variables, API assumptions, or scope change.
7. Summarize changed behavior, validation, and any remaining risk.

Create a Git checkpoint before and after a risky change. Do not commit secrets or generated local caches.

## Definition of done

A slice is complete only when:

- the participant-facing flow works in mock mode;
- errors and loading states are understandable;
- source and verification metadata remain visible;
- backend tests and frontend type checks pass;
- no secret is present in tracked files;
- relevant documentation is current.

## Change control

Treat a new data source, a new core workshop question, multi-source analysis, authentication, persistence, or deployment topology change as a scope change. Record the decision under `docs/decisions/` before implementing it.
