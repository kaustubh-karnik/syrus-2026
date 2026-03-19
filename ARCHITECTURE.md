# Project Architecture

## 1. Overview

This repository implements an autonomous incident-to-fix system with three main runtime surfaces:

1. A FastAPI backend for Jira ticket access and pipeline execution.
2. A Streamlit frontend for indexing an external code repository into Supabase.
3. A LangGraph-based agent pipeline that analyzes a Jira ticket, retrieves relevant code from vector storage, generates a fix, and patches a target repository on disk.

The repository does not contain the application being debugged. Instead, it operates on an external target repository configured through environment variables and indexing inputs.

## 2. Repository Structure

### Top level

- `README.md`: high-level project description.
- `requirements.txt`: Python dependencies.
- `backend/`: backend API, indexing script, test harness, and agent system.
- `frontend/streamlit/`: Streamlit UI for repository indexing.

### Backend

- `backend/app/main.py`: FastAPI entrypoint and HTTP routes.
- `backend/app/config.py`: environment-driven configuration.
- `backend/app/services/ticket_service.py`: service wrapper around Jira access.
- `backend/app/mcp/jira_client.py`: Jira integration client.
- `backend/app/agents/`: LangGraph nodes and shared state.
- `backend/app/utils/safety_checker.py`: patch safety validation.
- `backend/indexer.py`: clone/fetch, chunk, embed, and persist external repo code into Supabase.
- `backend/test_pipeline.py`: end-to-end CLI smoke test for the full flow.

### Frontend

- `frontend/streamlit/app.py`: UI that launches the backend indexer script as a subprocess.

## 3. Runtime Components

### 3.1 FastAPI backend

File: `backend/app/main.py`

Responsibilities:

- Exposes `GET /tickets` to list Jira tickets.
- Exposes `GET /tickets/{ticket_id}` to fetch a single Jira issue.
- Exposes `POST /analyze/{ticket_key}` to fetch one Jira issue and run the LangGraph pipeline.

This backend is a thin orchestration layer. It does not contain business logic itself; it delegates to `TicketService`, `JiraMCPClient`, and `run_pipeline()`.

### 3.2 Streamlit indexing UI

File: `frontend/streamlit/app.py`

Responsibilities:

- Accepts:
  - GitHub repository URL
  - repository identifier
  - git ref
  - local clone location
- Builds a JSON payload.
- Launches `backend/indexer.py` as a subprocess.
- Displays success/error details from the indexer JSON response.

This is not connected to the FastAPI app. It directly invokes the Python indexing script locally.

### 3.3 Standalone indexing service

File: `backend/indexer.py`

Responsibilities:

- Clones or refreshes an external repository.
- Checks out a requested branch/tag/commit.
- Walks the repo and filters files by supported extensions.
- Splits file content into chunks.
- Generates embeddings using `sentence-transformers/all-MiniLM-L6-v2`.
- Writes chunk metadata and embeddings into Supabase.

This script is effectively the ingestion pipeline for the vector database.

## 4. Agent Architecture

### 4.1 Graph engine

File: `backend/app/agents/pipeline.py`

The system uses `langgraph.StateGraph` with shared mutable state defined in `backend/app/agents/state.py`.

Pipeline nodes:

1. `analyze_ticket`
2. `search_code`
3. `generate_fix`
4. `patch_code`

Control flow:

- `analyze_ticket` -> conditional:
  - failure -> `END`
  - success -> `search_code`
- `search_code` -> `generate_fix`
- `generate_fix` -> conditional:
  - no fix / fix failure -> `END`
  - valid fix -> `patch_code`
- `patch_code` -> `END`

There is no validation node, test execution node, explanation node, or rollback node implemented in this repository, even though those are mentioned in comments or README materials.

### 4.2 Shared state

File: `backend/app/agents/state.py`

`AgentState` carries:

- input ticket payload
- analyzer outputs: bug type, keywords, likely files, service, confidence, root cause hint
- vector search outputs: retrieved files and combined code context
- fix generation output
- patch application result
- error and status fields

This shared state is the contract between all agent nodes.

### 4.3 Ticket analyzer agent

File: `backend/app/agents/ticket_analyzer.py`

Responsibilities:

- Takes Jira ticket fields.
- Prompts Groq-hosted `llama-3.3-70b-versatile`.
- Produces structured JSON:
  - `bug_type`
  - `keywords`
  - `likely_files`
  - `service`
  - `confidence`
  - `root_cause_hint`

This is the classification and search-query generation stage.

### 4.4 Vector search agent

File: `backend/app/agents/vector_search.py`

Responsibilities:

- Rebuilds a semantic query from the analyzer output.
- Embeds the query with the same sentence-transformers model used by the indexer.
- Calls Supabase RPC `match_embeddings`.
- Deduplicates results to file-level candidates.
- Produces:
  - ranked `retrieved_files`
  - a condensed `retrieved_code` prompt context for fix generation

Important detail:

- Retrieval is based on a Supabase database function that is not defined in this repo.
- The search does not filter by `repo_id` or `commit_sha`, so retrieval behavior depends entirely on how `match_embeddings` is implemented in the database.

### 4.5 Fix generator agent

File: `backend/app/agents/fix_generator.py`

Responsibilities:

- Normalizes Jira descriptions, including Atlassian Document Format-like structures.
- Builds an LLM prompt from ticket data and retrieved code snippets.
- Uses Groq `llama-3.3-70b-versatile` to return JSON containing:
  - target file
  - replacement code
  - reason
  - confidence
- Applies defensive parsing for malformed JSON responses.

This node does not produce a diff or structured patch. It only returns a candidate file path and a block of `fixed_code`.

### 4.6 Patch application agent

File: `backend/app/agents/patch_code.py`

Responsibilities:

- Rejects fixes below a confidence threshold of `80`.
- Runs a lightweight `SafetyChecker`.
- Resolves the target file from `TARGET_REPO_PATH`.
- Applies the patch using fuzzy window replacement, because the fix generator does not return original code or exact line numbers.
- Performs Python syntax validation on the full patched file when applicable.
- Saves a unified diff to `<TARGET_REPO_PATH>/backups/`.
- Writes the patched file back to disk.

Important operational behavior:

- The target repository is external to this repo.
- Patches are applied directly to that external repo on the local filesystem.
- Diff artifacts are preserved for possible rollback, but no rollback workflow exists in code.

## 5. Integrations

### 5.1 Jira

Files:

- `backend/app/mcp/jira_client.py`
- `backend/app/services/ticket_service.py`

Behavior:

- Uses the `jira` Python library to connect and fetch individual issues.
- Uses direct `requests.post()` to the Jira REST search endpoint for issue listing.

Notes:

- The code calls this an "MCP client", but it is not a Model Context Protocol server/client implementation in the protocol sense.
- It is a normal Python wrapper around Jira REST APIs.

### 5.2 Supabase + pgvector

Files:

- `backend/indexer.py`
- `backend/app/agents/vector_search.py`

Usage:

- Stores code chunks and vector embeddings in a `code_chunks` table.
- Reads semantic matches through an RPC named `match_embeddings`.

Inferred database objects required outside this repo:

- Supabase project
- `code_chunks` table with metadata columns and embedding column
- `match_embeddings(query_embedding, match_threshold, match_count)` function
- pgvector support in the backing Postgres instance

### 5.3 Groq LLM

Files:

- `backend/app/agents/ticket_analyzer.py`
- `backend/app/agents/fix_generator.py`

Usage:

- Both analysis and fix generation run through Groq.
- `OPENAI_API_KEY` is present in config but is not used anywhere in the codebase.

### 5.4 Git / filesystem

Files:

- `backend/indexer.py`
- `backend/app/agents/patch_code.py`

Usage:

- `indexer.py` clones/fetches repositories with `git`.
- `patch_code.py` modifies files in the configured target repo path.
- Backups are stored as unified diff files under the target repo.

## 6. Data Architecture

### 6.1 Configuration and secrets

File: `backend/app/config.py`

Environment variables expected:

- `OPENAI_API_KEY`
- `GROQ_API_KEY`
- `JIRA_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `TARGET_REPO_PATH`

Additional environment variables used by `backend/indexer.py`:

- `SUPABASE_SERVICE_ROLE_KEY`
- `REPOS_BASE_DIR`

Important inconsistency:

- The backend vector search uses `SUPABASE_KEY`.
- The indexer requires `SUPABASE_SERVICE_ROLE_KEY`.

This means indexing and retrieval may require different Supabase credentials.

### 6.2 Indexed code storage

The indexer writes chunk records with:

- `repo_id`
- `commit_sha`
- `path`
- `language`
- `symbol_name`
- `start_line`
- `end_line`
- `content`
- `content_hash`
- `embedding`

### 6.3 Ticket and pipeline state

There is no persistent job state, workflow database, or queue in this repo.

All pipeline state is:

- in-memory during LangGraph execution
- transient in the FastAPI request lifecycle
- optionally materialized as file diffs in the target repository

## 7. End-to-End Flows

### 7.1 Repository indexing flow

1. User opens Streamlit UI.
2. User enters repo URL, repo ID, git ref, and clone location.
3. Streamlit spawns `backend/indexer.py`.
4. Indexer clones/fetches the external repo.
5. Indexer chunks files and computes embeddings.
6. Indexer inserts new rows into Supabase `code_chunks`.

### 7.2 Ticket analysis and patch flow

1. Caller hits `POST /analyze/{ticket_key}`.
2. FastAPI fetches the Jira issue through `JiraMCPClient`.
3. LangGraph pipeline starts.
4. `ticket_analyzer` classifies the issue.
5. `vector_search` retrieves semantically related code from Supabase.
6. `fix_generator` asks Groq for a minimal fix.
7. `patch_code` validates and applies the fix to `TARGET_REPO_PATH`.
8. API returns final agent state, including patch result metadata.

## 8. MCP, Agents, and External Systems

### Agents implemented

- Ticket Analyzer
- Vector Search
- Fix Generator
- Patch Code

### MCP servers implemented

- None

What exists instead:

- `JiraMCPClient` is a normal Jira API wrapper placed under `backend/app/mcp/`.

### External systems required

- Jira Cloud or compatible Jira API
- Supabase project with pgvector-capable schema and RPC
- Groq API access
- A locally accessible target source repository to patch
- Git installed in the runtime environment

## 9. Gaps Between README and Code

The README describes a broader platform than what is currently implemented.

Claimed or implied in docs but not present in code:

- sandbox validation/test execution after patching
- Docker-based isolation
- resolution explanation/report generation
- rollback node
- true MCP servers
- OpenAI-powered runtime logic

Implemented in code:

- Jira fetch
- semantic code retrieval via Supabase
- Groq-based ticket analysis and fix generation
- direct patch application to a local repo

## 10. Risks and Architectural Constraints

### Tight coupling to local filesystem

`patch_code.py` edits files directly in `TARGET_REPO_PATH`. This makes the system environment-specific and hard to run safely in shared or production-like contexts.

### Weak patch precision

The fix generator returns only replacement code, not exact original ranges. Patching relies on fuzzy matching with a low acceptance threshold, which can patch the wrong block.

### Database retrieval ambiguity

`vector_search.py` does not scope retrieval by repository or commit. If Supabase contains embeddings for multiple repos or revisions, search correctness depends on undocumented database-side filtering.

### Missing execution validation

There is no automated test run, build run, or runtime verification after patch application.

### Mixed credential model

Indexing and retrieval use different Supabase environment variable names and potentially different privilege levels.

## 11. Practical Component Diagram

```text
                 +----------------------+
                 |   Streamlit UI       |
                 | frontend/streamlit   |
                 +----------+-----------+
                            |
                            | local subprocess
                            v
                 +----------------------+
                 | backend/indexer.py   |
                 +----------+-----------+
                            |
                            | git clone/fetch + chunk/embed
                            v
                 +----------------------+
                 | Supabase / pgvector  |
                 | code_chunks + RPC    |
                 +----------------------+


                 +----------------------+
                 | FastAPI backend      |
                 | backend/app/main.py  |
                 +----------+-----------+
                            |
                            | fetch issue
                            v
                 +----------------------+
                 | JiraMCPClient        |
                 | Jira REST / jira lib |
                 +----------------------+
                            |
                            | ticket
                            v
                 +----------------------+
                 | LangGraph pipeline   |
                 | analyze -> search    |
                 | -> fix -> patch      |
                 +----+-----------+-----+
                      |           |
        Groq LLM <----+           +----> local target repo on disk
   (analysis + fix gen)                 (patched via TARGET_REPO_PATH)
```

## 12. File-Level Ownership Map

- API layer: `backend/app/main.py`
- Jira access: `backend/app/mcp/jira_client.py`, `backend/app/services/ticket_service.py`
- Configuration: `backend/app/config.py`
- Workflow state machine: `backend/app/agents/pipeline.py`, `backend/app/agents/state.py`
- Ticket understanding: `backend/app/agents/ticket_analyzer.py`
- Code retrieval: `backend/app/agents/vector_search.py`
- Fix generation: `backend/app/agents/fix_generator.py`
- Patch safety and application: `backend/app/utils/safety_checker.py`, `backend/app/agents/patch_code.py`
- Vector ingestion: `backend/indexer.py`
- Manual end-to-end test harness: `backend/test_pipeline.py`

## 13. Bottom Line

This repo is best understood as an agent orchestrator around external systems:

- Jira supplies incident input.
- Supabase stores indexed code embeddings.
- Groq provides reasoning and code generation.
- A local external repository is the mutable patch target.

The architecture is functional as a prototype, but it is not yet a complete autonomous remediation platform because validation, rollback automation, isolation, and robust repository scoping are still missing.
