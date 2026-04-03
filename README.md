# Syrus 2026 Test Repo

## Start the project

### 1) Start backend (FastAPI)

From the repository root:

1. Go to backend folder
2. Create/activate virtual environment
3. Install Python dependencies
4. Start backend server

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r ..\requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend URL: `http://127.0.0.1:8000`

---

### 2) Start frontend (Next.js)

Open a new terminal from repository root:

1. Go to Next.js frontend folder
2. Install Node dependencies
3. Start dev server

```bash
cd frontend/nextjs
npm install
npm run dev
```

Frontend URL: `http://localhost:3000`

---

### 3) Required environment setup

- Backend reads env from root `.env`
- Frontend reads env from `frontend/nextjs/.env.local`

Minimum required frontend variable:

```env
NEXT_PUBLIC_BACKEND_BASE_URL=http://127.0.0.1:8000
```

---

## Architecture overview

This project follows a **Backend + Frontend + Agent Pipeline** architecture.

### A) Backend (`backend/app`)

- **API layer (FastAPI):** `backend/app/main.py`
  - Exposes endpoints for ticket fetch, repository clone, pipeline run, run history, and GitHub overview.
- **Agent workflow:** `backend/app/agents/`
  - Ticket analysis, vector retrieval, fix generation, patching, sandbox/test execution, pipeline orchestration.
- **Integrations (MCP/clients):** `backend/app/mcp/`
  - GitHub + Jira integrations.
- **Retrieval subsystem:** `backend/app/retrieval/`
  - Context bundling, repo profiling, graph/symbol helpers, validation planning.

### B) Frontend (`frontend/nextjs`)

- **UI layer (Next.js + React):** `src/app/page.tsx`
  - Mission-control dashboard for repository ingest, incident loading, pipeline execution, and report viewing.
- **API client layer:** `src/lib/api.ts`
  - Calls backend endpoints.
- **Shared contracts:** `src/lib/types.ts`
  - Request/response data models used by UI.

### C) End-to-end execution flow

1. User ingests a repository from frontend.
2. Frontend calls backend clone/index endpoints.
3. User loads/syncs incidents (Jira/manual).
4. Frontend starts pipeline (`/pipeline/solve-all-bugs`).
5. Backend runs ticket-to-fix agent pipeline and streams logs.
6. Frontend fetches final run report (`/pipeline/last-run`) and renders root cause, changes, and validation results.
