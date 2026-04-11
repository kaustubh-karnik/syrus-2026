# MPM Build - Automated Incident-to-Fix Pipeline

A full-stack AI system that ingests a repository, fetches incidents (Jira or manual), generates code fixes, validates them, and produces a structured report.

- **Backend:** FastAPI + LangGraph pipeline (`backend/`)
- **Frontend:** Next.js monitoring dashboard (`frontend/nextjs/`)
- **Integrations:** Jira MCP, GitHub MCP, Docker, Supabase
- **Primary LLM provider:** Cerebras (`qwen-3-235b-a22b-instruct-2507`)

---

## What this project does

For each incident/ticket, the system runs:

1. Ticket analysis
2. Semantic/vector retrieval
3. Fix generation
4. Patch application
5. Validation (local and/or Docker depending on planner + settings)
6. Aggregated reporting

The frontend streams live logs, tracks pipeline state, and renders per-ticket results including test breakdowns.

---

## Current architecture (live code)

```text
Frontend (Next.js, localhost:3000)
  └─ Calls FastAPI APIs + streams pipeline logs

Backend (FastAPI, port 8000)
  ├─ /agent/clone-repo                 (clone + active repo context)
  ├─ /pipeline/solve-all-bugs          (streaming run of backend/test_pipeline.py)
  ├─ /pipeline/last-run                (latest logs + parsed report)
  ├─ /pipeline/stop                    (graceful stop)
  ├─ /tickets, /tickets/{id}           (Jira service)
  ├─ /github/repositories/{o}/{r}/overview
  ├─ /analyze/{ticket_key}
  ├─ /analyze/batch
  └─ /debug/retrieval/{ticket_key}

Pipeline core (LangGraph)
  ticket_analyzer -> vector_search -> fix_generator -> patch_validator -> patch_code -> sandbox_runner -> recovery_agent

Report assembler
  backend/test_pipeline.py emits:
  PIPELINE_REPORT_JSON_START ... JSON ... PIPELINE_REPORT_JSON_END
```

---

## Repository/path model (important)

The pipeline no longer relies on a hardcoded repository path.

- Clone endpoint stores active runtime repo context in:
  - `.active_repo_context.json` at project root
- Pipeline endpoints require an **active absolute repo path**
- Clone destination must be:
  - Absolute path
  - Outside this `MPM-Build` repo

The frontend enforces this during ingest (`Local Workspace Path`).

---

## LLM providers and model selection

Configured in `backend/app/config.py` and used by analyzer/fix generator.

Provider priority:
1. **Cerebras** (if `CEREBRAS_API_KEY` present)
2. OpenRouter (fallback)
3. Groq (fallback)

Retry behavior can dynamically rotate provider order on LLM/transient failures (provider-switch strategy) instead of repeating the same static sequence.

Current default Cerebras model:
- `qwen-3-235b-a22b-instruct-2507`

Dependency present in root `requirements.txt`:
- `cerebras_cloud_sdk>=1.67.0`

---

## Pipeline flow details

### 1) Ingest repository
- Frontend: `POST /agent/clone-repo`
- Backend clone agent validates:
  - `repoId` (no traversal)
  - `localStorageLocation` absolute and external
- Optionally triggers Docker auto-heal after clone (`AUTO_RUN_DOCKER_AFTER_CLONE`)

### 2) Incident loading
- Jira sync via `GET /tickets`
- Or manual incident entry in UI

### 3) Streaming execution
- Frontend starts `POST /pipeline/solve-all-bugs`
- Backend launches `backend/test_pipeline.py` as subprocess
- Logs stream line-by-line to UI

### 4) Per-ticket execution
For each ticket, sequential pipeline with retry support:
- `ticket_analyzer_node`
- `vector_search_node`
- `fix_generator_node`
- `patch_validator_node` (contract + path + operation checks before patching)
- `patch_code_node`
- `sandbox_runner_node`
- `recovery_agent_node` (decides retry/finalize/switch-provider intent after validation)

Fail-fast rules now prevent downstream execution when fix generation or patch contract validation fails.

### 5) Validation strategy
Validation is adaptive:
- Candidate mode can be local or Docker from validation planner
- Python compile-only mode can force local compile checks
- Optional post-batch Docker full-suite validation can run after queue
- Optional post-batch auto-repair can attempt recovery

### 6) Reporting
`backend/test_pipeline.py` builds a detailed report:
- Summary: requested/processed/successful/halt info
- Per-ticket: status, attempts, failure type, provider attempts, patch validation, edits, promoted files, tests
- Optional post-batch validation/auto-repair sections

Frontend displays:
- Test totals and ticket totals
- Per-ticket result table
- **Per-ticket test breakdown** (selected/passed/failed test lists)
- **Per-ticket LLM routing telemetry** (providers used, provider-switch events, attempt timeline)

---

## API reference (current)

### Tickets
- `GET /tickets`
- `GET /tickets/{ticket_id}`

### Pipeline
- `POST /pipeline/solve-all-bugs` (streaming text)
- `GET /pipeline/last-run`
- `POST /pipeline/stop`

### Repository
- `POST /agent/clone-repo`
  - payload fields:
    - `repoUrl?: string`
    - `repoId: string`
    - `ref?: string`
    - `localStorageLocation?: string` (**required in practice for external absolute clone destination**)
    - `autoRunDocker?: boolean`

- `GET /github/repositories/{owner}/{repo}/overview`

### Analysis/debug
- `POST /analyze/{ticket_key}`
- `POST /analyze/batch`
- `GET /debug/retrieval/{ticket_key}`

---

## Setup

## Prerequisites

- Python 3.10+
- Node.js 18+
- Docker (if using Docker validation modes)
- Git
- Jira + GitHub credentials
- Supabase credentials
- At least one LLM provider key (Cerebras recommended)

### Recommended quick setup with Makefile (root)

- `make install-backend` → installs backend globally + `backend/.venv`
- `make install-frontend`
- `make install-all`
- `make run-backend`
- `make run-frontend`
- `make run-all`

### Manual backend setup

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ../requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Manual frontend setup

```bash
cd frontend/nextjs
npm install
npm run dev
```

---

## Environment variables

Root `.env` (`backend/app/config.py` reads from project root):

### Core integrations
- `JIRA_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`
- `JIRA_EXCLUDED_TICKET_KEYS`
- `GITHUB_TOKEN`
- `GITHUB_MCP_SERVER_COMMAND` (default `npx`)
- `GITHUB_MCP_SERVER_ARGS` (default `-y @modelcontextprotocol/server-github`)
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_KEY`)

### LLM providers
- `CEREBRAS_API_KEY`
- `CEREBRAS_MODEL` (default `qwen-3-235b-a22b-instruct-2507`)
- `OPENROUTER_API_KEY` (fallback)
- `OPENROUTER_BASE_URL`
- `OPENROUTER_MODEL`
- `OPENROUTER_APP_NAME`
- `OPENROUTER_HTTP_REFERER`
- `GROQ_API_KEY` (fallback)

### Repository/runtime
- `TARGET_REPO_ID` (optional metadata)
- `TARGET_REPO_COMMIT_SHA` (optional)
- `TARGET_REPO_PATH` (optional fallback; active runtime path is preferred)
- `GITHUB_REPO`
- `GITHUB_BASE_BRANCH`
- `REPOS_BASE_DIR` (optional default; frontend external path is preferred)

### Sandbox/pipeline behavior
- `SANDBOX_KEEP_DOCKER_CONTAINERS`
- `SANDBOX_DOCKER_PASS_ON_ANY_RELEVANT_TEST`
- `SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY`
- `SANDBOX_RUN_DOCKER_FULL_SUITE_AFTER_BATCH`
- `SANDBOX_AUTO_REPAIR_AFTER_POST_BATCH_FAILURE`
- `SANDBOX_AUTO_REPAIR_MAX_ATTEMPTS`
- `PATCH_DISABLE_VALIDATIONS`
- `AUTO_RUN_DOCKER_AFTER_CLONE`
- `LLM_MAX_GENERATION_RETRIES`
- `DOCKER_AUTOHEAL_MAX_CYCLES`
- `DOCKER_AUTOHEAL_FIX_ATTEMPTS`
- `FRONTEND_CORS_ORIGINS`

Frontend env (`frontend/nextjs/.env.local`):
- `NEXT_PUBLIC_BACKEND_BASE_URL`
- `NEXT_PUBLIC_TEAM_NAME` (optional)
- `NEXT_PUBLIC_AGENT_LABEL` (optional)
- `NEXT_PUBLIC_AGENT_CODE` (optional)
- `NEXT_PUBLIC_NAV_TAGLINE` (optional)

---

## Validation + metrics semantics

The dashboard intentionally reports two different scopes:

- **Tests:** aggregated across all selected tests in all tickets
- **Tickets:** one outcome per ticket

A ticket can be marked failed while still contributing passed tests (for example, 1 failed and 9 passed tests within that ticket).

The UI now includes per-ticket expandable test breakdowns showing:
- selected tests
- passed tests
- failed tests
- failed tests not present in selected set (edge case visibility)

---

## Useful files

- `backend/app/main.py` - API routes, streaming orchestration, active runtime repo context
- `backend/test_pipeline.py` - queue run + detailed report emission
- `backend/app/agents/pipeline.py` - LangGraph wiring + retry orchestration
- `backend/app/agents/sandbox_runner.py` - adaptive validation execution
- `backend/app/agents/fix_generator.py` - fix generation (Cerebras/OpenRouter/Groq)
- `backend/app/agents/ticket_analyzer.py` - ticket analysis (Cerebras/OpenRouter/Groq)
- `frontend/nextjs/src/app/page.tsx` - dashboard orchestration and reporting UI
- `Makefile` - install/run convenience targets

---

## Notes

- Docker behavior is configuration-driven; it is not hardcoded to always run for every validation step.
- Pipeline endpoints enforce active external repo context; clone first from the UI.
- Keep `.env` and secrets out of version control.
