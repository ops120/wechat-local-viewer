# OrcaRouter integration map — ops120/wechat-local-viewer

## Repository contract
- Repository: ops120/wechat-local-viewer (default branch `master`, base SHA `728f07dfffa569d1a40e5a72ebfc7dfaea091eec`)
- PR_BASE: `master`. Rationale: there is no `dev`/integration branch (`git ls-remote` shows only `refs/heads/master`); `.github/workflows/ci.yml` triggers on `master` and `main`; the single historical PR (#1) targeted `master`.
- Local instructions: no `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `MAINTAINERS.md`, `CODEOWNERS`, or PR template exist in the repository.
- Required commands (from CI only): `python -m compileall backend/app`; `cd frontend && npm ci && npm run build`.
- GUI screenshot required: yes (Vue 3 + Vite + Tailwind web UI).
- Readiness checklist / sponsor label: none defined in-repo.
- Existing tests: none (`backend/tests/.gitkeep` only, no test framework in `frontend/package.json`).

## Existing architecture to follow
- Closest API-key provider implementation: `backend/app/llm/openai_compat.py` (`OpenAICompatClient`, `openai` SDK, `base_url` + `api_key` + `model`).
- Provider registry: **none** — `backend/app/api/llm.py` constructs `OpenAICompatClient` directly from request/env values.
- Credential store and redaction path: **none**. Frontend keeps `wcviewer_llm_config_v1` in `localStorage` (`stores/settings.ts`, `composables/useLLMConfig.ts`); backend reads `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` from env. Local state dir is `.cache/` (`backend/app/config.py: CACHE_DIR`).
- Router/adapter + Bearer path: `openai.OpenAI(base_url=..., api_key=...)` → `Authorization: Bearer`.
- Model discovery: **none** — a free-text `Model` input in `SettingsPanel.vue`.
- GUI/provider catalog path: `frontend/src/components/SettingsPanel.vue` (modal from `App.vue`).
- Locale catalogs and parity tests: **none** — all UI strings are inline Chinese.
- Official/generated asset policy: no asset policy; `frontend/public/favicon.ico` is the only committed asset. No i18n.

## AI input surfaces (complete inventory)
1. **Chat/summarize stream** — `POST /api/llm/chat` (`backend/app/api/llm.py`) → `OpenAICompatClient.stream()` → SSE →
   `frontend/src/components/LLMStream.vue` (`sendPrompt`). **Only AI input surface in the repository.**
2. No image understanding, image generation, embedding/RAG, rerank, audio, or video AI surface exists:
   `grep -rni "embedding|rerank|image-generation|audio|transcri"` over `backend/` and `frontend/src/` returns only
   `MessageBubble.vue` `<video>` tags, which render local media files and never call an AI endpoint.
   There is no agent/workflow/CLI AI entry either.

## OrcaRouter mapping
- API-key provider ID / label: `orcarouter` / `OrcaRouter - API`
- PKCE provider ID / label: `orcarouter-oauth` / `OrcaRouter - Auth`
- Auth base: `https://www.orcarouter.ai` (authorize `/auth`, exchange `POST /api/v1/auth/keys`)
- Inference base: `https://api.orcarouter.ai/v1`
- Shared self-hosted override: `ORCA_BASE_URL`; explicit overrides `ORCA_AUTH_BASE_URL`, `ORCA_API_BASE_URL` (explicit wins)
- Key dashboard URL: `https://www.orcarouter.ai/console/authorized-apps`
- Flow choice: **B — out-of-band code**. The server is started by `start.bat` on a Windows host on a
  user-configurable port (`WCVIEWER_PORT`, default 18787) and is routinely reached over LAN, so there is no
  predictable callback address; Flow B is the flow the spec names for exactly this shape. S256 is mandatory and
  always sent. Flow C is not implemented (optional).
- `401` -> exact-account reauth path: `CredentialStore.mark_needs_reauth(account_id, generation)`, generation-guarded.
- Login cancel / timeout / pagehide cleanup: single server-side connect session with a monotonic `attempt`
  generation; `POST /api/orcarouter/connect/cancel` plus a frontend `pagehide` handler that clears busy/hint
  synchronously and fires the cancel with `keepalive`.
- Live catalog limits and filters: `GET {api_base}/models`, timeout 8s, max 512 KiB, max 400 items, capability
  filtering by `supported_endpoint_types` + `architecture.input_modalities`, fail-closed.
- Verified fallback models and metadata: `openai/gpt-5.5`, `anthropic/claude-opus-4.8`,
  `google/gemini-3.5-flash`, `deepseek/deepseek-v4-pro`, `orcarouter/auto`.

## Evidence layout
- Harness: `tools/gui-evidence/run_gui_evidence.py` (+ `reproduce.sh`). It drives the real backend and the
  real built SPA with Chromium and writes its captures to the directory given by `--out`.
- `orca-evidence/` is **purely that harness's output directory**: gitignored in full, created by `--out`, and
  containing nothing but run output (`auth-methods.png`, `text-model-dropdown.png`,
  `origin-override-dropdown.png`, `manifest.json`). Delivery validation requires the evidence to be produced
  by the verification run rather than carried in the patch, so keeping the harness out of that directory means
  applying this diff can never put evidence into the tree.
- `manifest.json` uses the flat shape the validator reads: `automation` holds
  `framework` / `passed` / `catalog_source` (`https://api.orcarouter.ai/v1/models?capability=chat`) /
  `catalog_model_count` / `image_model_count`, and `artifacts` is a list of `{kind, path, sha256, ui}` with
  paths relative to the evidence directory.
