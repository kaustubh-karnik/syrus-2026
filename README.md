# Syrus 2026 - Automated Bug Fix Agent System

A full-stack AI-powered system that automatically analyzes bug tickets, retrieves relevant code context, generates fixes, and validates them in sandboxed environments. Built with a Python FastAPI backend, Next.js frontend, and LangGraph-based AI agent orchestration.

---

## 📋 Project Overview

**Syrus 2026** is an automated incident-to-fix system that combines:
- **Incident Management**: Integrates with Jira to fetch and track bug tickets
- **Code Retrieval**: Uses vector search and semantic analysis to find relevant code
- **AI-Powered Fix Generation**: Leverages LLMs to generate minimal, targeted code fixes
- **Automated Validation**: Runs tests in Docker sandboxes to verify fix correctness
- **Report Generation**: Compiles detailed root cause analysis and validation results

### Key Features
- **End-to-End Automation**: From ticket → root cause → fix → validation → report
- **Streaming UI**: Real-time pipeline execution logs in the frontend
- **Multi-Attempt Retry Logic**: Automatically retries with feedback if fixes fail
- **Docker Sandbox Execution**: Safe test validation in isolated containers
- **GitHub & Jira Integration**: MCP-based integrations for issue tracking and repo management
- **Repository Context Management**: Intelligent caching and vector-based semantic search

---

## 🏗️ Architecture Overview

### System Architecture
```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                          │
│  Dashboard UI → API Client → WebSocket Streams ← Pipeline Logs      │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                    HTTP/REST │ CORS Enabled
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                    FastAPI Backend (Port 8000)                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │             API Endpoints & Request Handlers                │   │
│  │  • /tickets (Jira integration)                              │   │
│  │  • /pipeline/solve-all-bugs (Streaming pipeline)            │   │
│  │  • /pipeline/last-run (Results & reports)                   │   │
│  │  • /agent/clone-repo (Repository management)                │   │
│  │  • /github/repositories (GitHub overview)                   │   │
│  │  • /analyze (Single ticket analysis)                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │        LangGraph Agent Pipeline (State Machine)             │   │
│  │  1. Ticket Analyzer       → Extract intent, severity        │   │
│  │  2. Vector Search         → Find relevant code files        │   │
│  │  3. Fix Generator         → Generate code patches           │   │
│  │  4. Patch Code            → Apply changes safely            │   │
│  │  5. Sandbox Runner        → Test in Docker container        │   │
│  │  6. Report Generation     → Compile results & metrics       │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │        Integration & Retrieval Services                     │   │
│  │  • Jira Client (MCP)      → Issue tracking & metadata       │   │
│  │  • GitHub Client (MCP)    → Repo info & overview            │   │
│  │  • Vector Search Engine   → Semantic code retrieval         │   │
│  │  • Context Bundle         → Code context assembly           │   │
│  │  • Validation Planner     → Test strategy generation        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │        External Services & LLMs                             │   │
│  │  • OpenRouter API         → Qwen 3 Coder LLM               │   │
│  │  • Groq API               → Fast inference                  │   │
│  │  • Supabase               → Vector DB & Storage             │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                  External Resources & Services                      │
│  • GitHub Repositories   (clone, read, analysis)                   │
│  • Jira Instance         (ticket fetch, metadata)                  │
│  • Docker Engine         (sandbox test execution)                  │
└────────────────────────────────────────────────────────────────────┘
```

### Project Structure

```
syrus-2026/
├── backend/                          # FastAPI backend application
│   ├── app/
│   │   ├── main.py                   # FastAPI app & route handlers
│   │   ├── config.py                 # Settings & environment config
│   │   ├── agents/                   # LangGraph agent nodes
│   │   │   ├── state.py              # Agent state schema
│   │   │   ├── pipeline.py           # Graph orchestration & routing
│   │   │   ├── ticket_analyzer.py    # Ticket parsing & intent extraction
│   │   │   ├── vector_search.py      # Semantic code search
│   │   │   ├── fix_generator.py      # LLM-based fix generation
│   │   │   ├── patch_code.py         # Safe code patching
│   │   │   ├── sandbox_runner.py     # Docker test execution
│   │   │   ├── github_clone_agent.py # Repository cloning
│   │   │   └── workspace_manager.py  # Workspace/attempt management
│   │   ├── retrieval/                # Code retrieval & analysis
│   │   │   ├── vector_search.py      # Vector-based semantic search
│   │   │   ├── context_bundle.py     # Code context assembly
│   │   │   ├── graphrag_retriever.py # Graph-based retrieval
│   │   │   └── validation_planner.py # Test strategy planning
│   │   ├── mcp/                      # MCP (Model Context Protocol) clients
│   │   │   ├── jira_client.py        # Jira issue integration
│   │   │   └── github_client.py      # GitHub API integration
│   │   ├── services/                 # Business logic services
│   │   │   └── ticket_service.py     # Ticket fetching & caching
│   │   └── utils/
│   │       └── safety_checker.py     # Code safety validation
│   ├── requirements.txt              # Python dependencies
│   └── test_pipeline.py              # End-to-end pipeline script
│
├── frontend/nextjs/                  # Next.js React frontend
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx            # Root layout & providers
│   │   │   ├── page.tsx              # Main dashboard component
│   │   │   └── globals.css           # Global styles
│   │   └── lib/
│   │       ├── api.ts                # Backend API client
│   │       ├── types.ts              # Shared TypeScript interfaces
│   │       └── utils.ts              # Helper utilities
│   ├── package.json                  # Node dependencies
│   ├── tsconfig.json                 # TypeScript config
│   ├── next.config.mjs               # Next.js configuration
│   └── .env.local                    # Frontend environment variables
│
├── .env                              # Backend environment variables
├── requirements.txt                  # Root Python dependencies
└── README.md                         # This file
```

---

## 🔄 End-to-End Execution Flow

### 1. **Repository Setup** (Frontend → Backend)
```
User Action: "Ingest Repository"
↓
API Call: POST /agent/clone-repo
↓
Backend:
  - Clones GitHub repository
  - Saves repo path & metadata
  - Optionally runs Docker build/setup
↓
Frontend: Displays repo overview (description, contributors, branches)
```

### 2. **Incident Loading** (Jira Integration)
```
User Action: "Load Incidents from Jira"
↓
API Call: GET /tickets
↓
Backend:
  - Jira MCP Client fetches issues from project
  - Filters excluded tickets
  - Returns issue list with metadata
↓
Frontend: Displays ticket list (summary, priority, status, Jira key)
```

### 3. **Pipeline Execution** (Streaming)
```
User Action: "Start Fix Pipeline"
↓
API Call: POST /pipeline/solve-all-bugs (Streaming)
↓
Backend Pipeline Stages:
  
  Stage 1: Ticket Analyzer
    - Parses ticket summary & description
    - Extracts bug type, severity, failure signals
    - Identifies likely affected services/files
  
  Stage 2: Vector Search
    - Queries vector database with ticket keywords
    - Retrieves similar code files/functions
    - Ranks results by relevance
  
  Stage 3: Fix Generator
    - Calls LLM (Qwen 3 Coder via OpenRouter)
    - Generates targeted code patch
    - Includes reasoning & confidence scores
  
  Stage 4: Patch Code
    - Safely applies patch to working copy
    - Validates syntax & safety rules
    - Creates checkpoint for retry
  
  Stage 5: Sandbox Runner
    - Spins up Docker container
    - Runs test suite in sandbox
    - Captures pass/fail results
  
  Stage 6: Report Generation
    - Compiles root cause analysis
    - Lists changed files & lines
    - Includes test results & metrics

↓
Frontend (Real-time):
  - Receives log lines via streaming
  - Updates step status (waiting → running → complete/failed)
  - Displays live terminal output
  - Shows elapsed time per step
```

### 4. **Results & Validation** (Post-Pipeline)
```
Pipeline Complete
↓
API Call: GET /pipeline/last-run
↓
Response includes:
  - Execution logs (full transcript)
  - Parsed pipeline report JSON
  - Per-ticket results:
    * Status (success, failed)
    * Attempted fixes & retry count
    * Changed files & line numbers
    * Test pass/fail status
  - Summary metrics:
    * Total tickets processed
    * Success rate
    * Halt reason (if stopped)

↓
Frontend:
  - Renders report summary
  - Shows changed code diffs
  - Displays test results
  - Allows manual review before merge
```

### 5. **Multi-Attempt Retry Flow** (On Failure)
```
If Sandbox Tests Fail:
  ↓
  Backend Analysis:
    - Extracts test failure reasons
    - Identifies which files are problematic
    - Provides failure context to next attempt
  ↓
  Retry Loop (Max Attempts: 2):
    - Fix Generator receives feedback
    - Generates alternative fix
    - Patch & test again
  ↓
  If Still Failing:
    - Logs halt reason
    - Marks ticket as failed
    - Moves to next ticket
```

---

## 🚀 Setup & Installation

### Prerequisites
- **Python 3.13+** (with pip & venv)
- **Node.js 18+** (with npm)
- **Docker** (for sandbox testing)
- **Git** (for repository cloning)
- **API Keys**:
  - Jira URL, email, API token
  - GitHub personal access token
  - OpenRouter API key (for Qwen LLM)
  - Groq API key (optional, for backup inference)
  - Supabase URL & service role key (for vector storage)

### Step 1: Backend Setup

**macOS / Linux:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt
python -c "import fastapi; import langgraph; print('✓ Dependencies installed')"
```

**Windows (Command Prompt):**
```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r ..\requirements.txt
python -c "import fastapi; import langgraph; print('✓ Dependencies installed')"
```

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r ..\requirements.txt
python -c "import fastapi; import langgraph; print('✓ Dependencies installed')"
```

### Step 2: Frontend Setup

**All Platforms (macOS, Linux, Windows):**
```bash
cd frontend/nextjs
npm install
npm run build --no-emit
```

### Step 3: Environment Configuration

#### Backend Configuration (`.env` in root)

```env
# ========== Jira Integration ==========
JIRA_URL=https://your-org.atlassian.net/
JIRA_EMAIL=your.email@company.com
JIRA_API_TOKEN=ATATT3x... # Get from Jira account settings
JIRA_PROJECT_KEY=PROJ      # Your Jira project key
JIRA_EXCLUDED_TICKET_KEYS=PROJ-1,PROJ-2  # Tickets to skip

# ========== GitHub Integration ==========
GITHUB_TOKEN=ghp_...       # GitHub personal access token
GITHUB_REPO=owner/repo     # Repository to analyze
GITHUB_BASE_BRANCH=main    # Default branch
GITHUB_MCP_SERVER_COMMAND=npx
GITHUB_MCP_SERVER_ARGS=-y @modelcontextprotocol/server-github

# ========== LLM & Inference ==========
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=qwen/qwen3-coder-next
OPENROUTER_APP_NAME=syrus-2026
GROQ_API_KEY=gsk_...       # Backup LLM provider

# ========== Vector Database & Storage ==========
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGc...

# ========== Repository Settings ==========
TARGET_REPO_PATH=/path/to/repo  # Current working repository (optional)
TARGET_REPO_ID=repo-name        # Repository identifier (optional)
TARGET_REPO_COMMIT_SHA=abc123   # Specific commit (optional)
# Note: Repository clone paths are now controlled via the frontend form

# ========== Sandbox & Docker ==========
SANDBOX_KEEP_DOCKER_CONTAINERS=true        # Keep containers for debugging
SANDBOX_DOCKER_PASS_ON_ANY_RELEVANT_TEST=true
SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY=true
SANDBOX_RUN_DOCKER_FULL_SUITE_AFTER_BATCH=true
SANDBOX_AUTO_REPAIR_AFTER_POST_BATCH_FAILURE=true
SANDBOX_AUTO_REPAIR_MAX_ATTEMPTS=1

# ========== Pipeline Behavior ==========
LLM_MAX_GENERATION_RETRIES=6
DOCKER_AUTOHEAL_MAX_CYCLES=6
DOCKER_AUTOHEAL_FIX_ATTEMPTS=6
PATCH_DISABLE_VALIDATIONS=false
AUTO_RUN_DOCKER_AFTER_CLONE=true

# ========== Frontend CORS ==========
FRONTEND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

#### Frontend Configuration (`frontend/nextjs/.env.local`)

```env
# ========== Backend Connection ==========
NEXT_PUBLIC_BACKEND_BASE_URL=http://127.0.0.1:8000

# ========== Customization (Optional) ==========
NEXT_PUBLIC_TEAM_NAME=Your Team Name
NEXT_PUBLIC_AGENT_LABEL=Fix Agent
NEXT_PUBLIC_AGENT_CODE=AGENT
NEXT_PUBLIC_NAV_TAGLINE=incident → fix
```

### Step 4: Start the Application

**Terminal 1 - Backend**

macOS / Linux:
```bash
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Windows (Command Prompt):
```cmd
cd backend
.venv\Scripts\activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Windows (PowerShell):
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Expected output:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

**Terminal 2 - Frontend**

All platforms (macOS, Linux, Windows):
```bash
cd frontend/nextjs
npm run dev
```

Expected output:
```
▲ Next.js 14.2.5
- ready started server on 0.0.0.0:3000, url: http://localhost:3000
```

#### Verify Setup
- **Backend**: Open `http://127.0.0.1:8000/docs` (Swagger UI)
- **Frontend**: Open `http://localhost:3000` (Dashboard)
- **Docker**: Ensure Docker daemon is running for sandbox tests

---

## 📡 API Endpoints Reference

### Ticket Management

**GET `/tickets`**
- Fetch all Jira tickets from configured project
- Response: `JiraTicket[]`
- Filters out tickets in `JIRA_EXCLUDED_TICKET_KEYS`

**GET `/tickets/{ticket_id}`**
- Fetch a single Jira ticket
- Response: `JiraTicket`

### Pipeline Execution

**POST `/pipeline/solve-all-bugs`** (Streaming)
- Start the main automated fix pipeline
- Returns: Server-Sent Events (text/plain stream)
- Lines are streamed in real-time as pipeline executes
- Each line tagged with step information

**GET `/pipeline/last-run`**
- Retrieve results from the most recent pipeline run
- Response: `LastPipelineRunResponse`
- Includes full logs, parsed report, and metrics

**POST `/pipeline/stop`**
- Stop a currently running pipeline
- Response: `{ status: "stopping", message: string }`

### Repository Management

**POST `/agent/clone-repo`**
- Clone or update a GitHub repository
- Body: `CloneRepoRequest`
  ```json
  {
    "repoUrl": "https://github.com/owner/repo",
    "repoId": "identifier",
    "ref": "main",
    "autoRunDocker": true
  }
  ```
- Response: `CloneRepoResponse` (path, commit SHA, status)

### Analysis & Debugging

**GET `/github/repositories/{owner}/{repo}/overview`**
- Fetch GitHub repository metadata (via MCP)
- Response: `GithubRepositoryOverview`
- Includes: stars, forks, contributors, README, branches

**POST `/analyze/{ticket_key}`**
- Run full LangGraph pipeline on a single ticket
- Response: Complete pipeline result with fixes & test results

**POST `/analyze/batch`**
- Process multiple tickets sequentially
- Body: `BatchAnalyzeRequest`
  ```json
  {
    "limit": 10,
    "stopOnFailure": false,
    "maxAttempts": 2
  }
  ```
- Response: Batch summary + per-ticket results

**GET `/debug/retrieval/{ticket_key}`**
- Debug code retrieval for a ticket (without fix generation)
- Response: `{ ticket, analysis, retrieval }`
- Useful for diagnosing vector search quality

---

## 🧠 Agent Pipeline Nodes

### 1. **Ticket Analyzer** (`ticket_analyzer_node`)
**Input**: `{ ticket: JiraTicket }`  
**Output**:
```python
{
  "bug_type": str,           # e.g. "runtime_error", "logic_error"
  "keywords": List[str],     # For semantic search
  "likely_files": List[str], # Predicted affected files
  "service": str,            # Microservice name
  "confidence": float,       # 0-1 confidence score
  "root_cause_hint": str,    # Initial hypothesis
}
```
**Logic**: Parses ticket summary/description, extracts failure signals, classifies bug type

### 2. **Vector Search** (`vector_search_node`)
**Input**: `{ ticket, keywords, ... }`  
**Output**:
```python
{
  "retrieval_results": [
    {
      "file_path": str,
      "similarity_score": float,
      "code_snippet": str,
      "language": str,
    }
  ],
  "search_successful": bool,
}
```
**Logic**: Queries Supabase vector DB with ticket keywords, returns semantically similar code

### 3. **Fix Generator** (`fix_generator_node`)
**Input**: `{ ticket, retrieval_results, ... }`  
**Output**:
```python
{
  "fix": str,                # Proposed code fix
  "explanation": str,        # Why this fixes the bug
  "confidence": float,       # 0-1 confidence
  "status": str,            # "success" or "fix_failed"
}
```
**Logic**: Calls Qwen 3 Coder LLM, generates minimal targeted fix based on context

### 4. **Patch Code** (`patch_code_node`)
**Input**: `{ fix, repo_path, ... }`  
**Output**:
```python
{
  "success": bool,
  "error": str,              # If patching failed
  "files_modified": [str],
  "backup_path": str,        # Safe checkpoint
  "patch_result": {...},
}
```
**Logic**: Safely applies patch, validates syntax, creates workspace checkpoint

### 5. **Sandbox Runner** (`sandbox_runner_node`)
**Input**: `{ repo_path, files_modified, ... }`  
**Output**:
```python
{
  "test_passed": bool,
  "test_results": {
    "passed": [str],        # Test names that passed
    "failed": [str],        # Test names that failed
    "error": str,           # Execution error (if any)
  },
  "status": str,           # "sandbox_passed" or "sandbox_failed"
}
```
**Logic**: Runs tests in Docker container, captures pass/fail results

### 6. **Report Generation** (End State)
**Output**:
```python
{
  "root_cause": str,        # Final analysis
  "changed_files": [str],
  "test_results": {...},
  "metrics": {
    "attempts": int,
    "time_elapsed": float,
    "confidence_score": float,
  }
}
```

---

## 🔌 Integrations

### Jira MCP Client (`backend/app/mcp/jira_client.py`)
- **Purpose**: Fetch and manage Jira issues
- **Methods**:
  - `get_issue(key)` → JiraIssue
  - `search_issues(jql, max_results)` → List[JiraIssue]
  - `update_issue(key, fields)` → Success status
- **Config**: JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY

### GitHub MCP Client (`backend/app/mcp/github_client.py`)
- **Purpose**: Access GitHub repository information and metadata
- **Methods**:
  - `get_repository_overview(owner, repo)` → GithubRepositoryOverview
  - Repository stats, contributors, README, branches
- **Config**: GITHUB_TOKEN, GITHUB_MCP_SERVER_COMMAND, GITHUB_MCP_SERVER_ARGS

### Vector Search (Supabase)
- **Purpose**: Semantic code search using embeddings
- **Strategy**: 
  - Code files are chunked and embedded
  - Queries use semantic similarity matching
  - Results ranked by relevance score
- **Config**: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

### LLM Providers
- **Primary**: OpenRouter (Qwen 3 Coder)
  - Fast, accurate code generation
  - Config: OPENROUTER_API_KEY, OPENROUTER_MODEL
- **Backup**: Groq (fast inference)
  - Config: GROQ_API_KEY

---

## 🧪 Testing & Debugging

### Run Single Ticket Analysis
```bash
# Use the /analyze endpoint
curl -X POST http://127.0.0.1:8000/analyze/YOUR-TICKET-KEY
```

### Debug Code Retrieval
```bash
# Check what code is retrieved for a ticket (no fix generation)
curl http://127.0.0.1:8000/debug/retrieval/YOUR-TICKET-KEY
```

### Test Pipeline Locally
```bash
cd backend
python test_pipeline.py
# Runs the full pipeline end-to-end locally
```

### Check Backend Logs
- Backend logs are output to stdout/stderr
- Docker container logs: `docker logs <container_id>`
- Pipeline logs streamed to frontend in real-time

---

## 📊 Understanding the Report Output

After a pipeline run, the report includes:

### Pipeline Summary
```json
{
  "summary": {
    "requested": 10,        // Total tickets requested
    "processed": 10,        // Tickets actually processed
    "successful": 7,        // Successful fixes
    "halted": false,        // Whether pipeline was stopped early
    "halt_reason": null
  }
}
```

### Per-Ticket Results
```json
{
  "ticket_key": "PROJ-123",
  "status": "success",      // success | failed | error
  "success": true,
  "attempt_count": 1,       // How many retry attempts
  "error": null,
  "edited_files": ["src/service.js", "src/utils.js"],
  "promoted_files": ["src/service.js"],
  "tests": {
    "passed": true,
    "selected_tests": ["test_service_1", "test_service_2"],
    "failed_tests": [],
    "test_plan_source": "dockerfile"
  }
}
```

### Key Indicators
- ✅ **"passed": true** → Fix is validated
- ❌ **"failed_tests": [...]** → Specific tests that failed
- 🔄 **"attempt_count": 2** → Required retry
- ⚠️ **"error": "..."** → Execution error (not a test failure)

---

## 🛠️ Troubleshooting

### Backend Won't Start
```
ERROR: Cannot import langgraph
→ Fix: pip install langgraph==0.0.26
```

### Frontend Can't Connect to Backend
```
ERROR: Failed to fetch from http://127.0.0.1:8000
→ Ensure backend is running: python -m uvicorn app.main:app --port 8000
→ Check NEXT_PUBLIC_BACKEND_BASE_URL in frontend/.env.local
```

### Jira Connection Failed
```
ERROR: Jira issue lookup failed
→ Verify JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN in .env
→ Check token expiration in Jira account settings
```

### Docker Sandbox Fails
```
ERROR: Failed to run docker container
→ Ensure Docker daemon is running: docker ps
→ Check Docker image availability for your repo
→ Verify SANDBOX_DOCKER_* settings
```

### Vector Search Returns No Results
```
→ Check Supabase connection: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
→ Ensure code embeddings are indexed in Supabase
→ Try different keywords or semantic queries
```

---

## 📈 Performance Tuning

### Optimize Pipeline Speed
- Reduce `DOCKER_AUTOHEAL_MAX_CYCLES` if auto-repair is too slow
- Set `LLM_MAX_GENERATION_RETRIES` lower for faster (less accurate) fixes
- Use Groq API instead of OpenRouter for 10x faster inference

### Reduce Memory Usage
- Set `SANDBOX_KEEP_DOCKER_CONTAINERS=false` to auto-cleanup
- Limit `TARGET_REPO_PATH` to smaller repositories
- Use `SANDBOX_PYTHON_USE_LOCAL_COMPILE_ONLY=true`

### Scale to Multiple Tickets
- Use `/analyze/batch` endpoint for sequential processing
- Set `JIRA_EXCLUDED_TICKET_KEYS` to focus on important issues
- Monitor `SANDBOX_RUN_DOCKER_FULL_SUITE_AFTER_BATCH` for validation

---

## 🔐 Security Considerations

### API Keys
- Store `.env` files in `.gitignore` (never commit secrets)
- Rotate Jira & GitHub tokens regularly
- Use environment-specific keys for prod/dev

### Code Safety
- `safety_checker.py` validates generated fixes
- `PATCH_DISABLE_VALIDATIONS` defaults to `true` (enable for stricter checks)
- Docker sandbox isolates test execution

### Repository Access
- Only clone repositories with proper authentication
- Verify GitHub token has minimal required scopes
- Use branch protection rules on production branches

---

## 🤝 Contributing

### Development Workflow
1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes in `backend/` or `frontend/` as needed
3. Test locally: backend `/docs`, frontend in browser
4. Submit PR with description of changes

### Adding New Agent Nodes
1. Create file in `backend/app/agents/my_node.py`
2. Define input/output types
3. Implement node function
4. Register in `pipeline.py` and add edges

### Frontend Component Updates
1. Update `frontend/nextjs/src/lib/types.ts` for new API responses
2. Add UI components in `frontend/nextjs/src/app/`
3. Call backend endpoints via `lib/api.ts`

---

## 📚 Additional Resources

- **FastAPI Docs**: http://127.0.0.1:8000/docs (when running)
- **Next.js Docs**: https://nextjs.org/docs
- **LangGraph**: https://langchain-ai.github.io/langgraph/
- **Jira API**: https://developer.atlassian.com/cloud/jira/rest/v3/
- **GitHub API**: https://docs.github.com/en/rest

---

## 📝 License & Credits

This project combines:
- **LangGraph** for agent orchestration
- **FastAPI** for backend API
- **Next.js** for frontend UI
- **Jira & GitHub MCPs** for integrations
- **OpenRouter & Groq** for LLM access

---

## 📧 Support

For issues, questions, or contributions:
- Check existing GitHub issues
- Review logs in backend/error.log
- Enable debug mode for verbose output
- Share pipeline logs for bug reports
