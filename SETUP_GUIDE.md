# MPM Build - Setup & Quick Start Guide

## Overview

MPM Build is an automated incident-to-fix system with:
- **Backend**: FastAPI (Python)
- **Frontend**: Next.js/React (TypeScript)
- **Integration**: Jira, GitHub, Docker, Supabase

---

## Quick Start (5 Minutes)

### 1. Environment File Setup

Create/edit `.env` in the root directory with required keys:

```env
# Jira Integration
JIRA_URL=https://your-org.atlassian.net/
JIRA_EMAIL=your.email@company.com
JIRA_API_TOKEN=your_token_here
JIRA_PROJECT_KEY=YOUR_PROJECT_KEY

# GitHub Integration
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPO=owner/repo-name
GITHUB_BASE_BRANCH=main

# LLM & AI
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=qwen/qwen3-coder-next
GROQ_API_KEY=your_key_here

# Vector Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_key_here
```

**Important**: Do NOT set `REPOS_BASE_DIR` - it's now controlled via the frontend form.

### 2. Start Backend

**macOS / Linux:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Windows (Command Prompt):**
```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r ..\requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r ..\requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start Frontend (New Terminal)

**All Platforms:**
```bash
cd frontend/nextjs
npm install
npm run dev
```

### 4. Open Dashboard

Open `http://localhost:3000` in your browser.

---

## Using the System

### Repository Ingestion

1. Fill the form:
   - **GitHub Repository URL**: `https://github.com/owner/repo.git`
   - **Target Branch**: `main`
   - **Folder Name**: `my-repo`
   - **Local Workspace Path**: Choose where to clone

2. **Local Workspace Path** options:
   - **Relative**: `./repos` → clones to `PROJECT_ROOT/repos/my-repo`
   - **Absolute**: `/Users/user/code` → clones to `/Users/user/code/my-repo`
   - **Home dir**: `~/code/repos` → expands and clones there
   - **Leave blank**: Uses `./repos` as default

3. Click **"Ingest Repository"**

---

## File Structure

```
syrus-2026/
├── backend/              # FastAPI server
│   ├── app/
│   │   ├── main.py       # API routes
│   │   ├── config.py     # Settings (NEW: simple path resolution)
│   │   ├── agents/       # LangGraph pipeline
│   │   ├── mcp/          # GitHub & Jira clients
│   │   └── retrieval/    # Code search & context
│   └── requirements.txt
│
├── frontend/nextjs/      # Next.js dashboard
│   ├── src/
│   │   ├── app/          # Pages & layout
│   │   └── lib/          # API client & types
│   └── package.json
│
├── .env                  # Backend config (no REPOS_BASE_DIR!)
├── ACTION_PLAN.txt       # This setup guide
└── README.md             # Full documentation
```

---

## Recent Fixes & Changes

### Problem Solved
- ❌ **Was**: Hardcoded Windows path in `.env` broke on macOS
- ✅ **Now**: User controls paths via frontend form

### Code Changes
1. **config.py**
   - Added: `resolve_path_to_absolute(path, base_for_relative)`
   - Removed: Complex Windows path detection
   
2. **github_clone_agent.py**
   - Uses frontend input directly
   - No fallback to config values
   - Smart default: `./repos` if blank

### Cross-Platform
✅ Works on macOS  
✅ Works on Windows  
✅ Works on Linux  

---

## Troubleshooting

### Backend won't start

**Python not found:**
```bash
# Ensure Python 3.13+ is installed
python --version
# or try
python3 --version
```

**Activation failed:**
```bash
# macOS/Linux
source .venv/bin/activate

# Windows (if above fails)
source .venv/Scripts/activate  # Git Bash
```

### Frontend won't start

**Node not found:**
```bash
# Ensure Node 18+ is installed
node --version
npm --version
```

**Port in use:**
```bash
# Frontend uses port 3000, backend uses 8000
# If ports are busy, check:
# macOS/Linux:
lsof -i :3000
lsof -i :8000

# Windows:
netstat -ano | findstr :3000
netstat -ano | findstr :8000
```

### Repos cloning to wrong location

**Check logs:**
```
[CloneAgent] localStorageResolved (absolute)=/correct/path
[CloneAgent] os.path.isabs(localStorageResolved)=True
```

Should show absolute path, not containing `C:\` on macOS.

**Check frontend form:**
- Verify "Local Workspace Path" is filled correctly
- Try absolute path: `/Users/username/code/repos`

---

## Environment Variables

### Required

```env
JIRA_URL              # Jira instance URL
JIRA_EMAIL            # Jira account email
JIRA_API_TOKEN        # Jira API token
GROQ_API_KEY          # LLM inference
SUPABASE_URL          # Vector database
GITHUB_TOKEN          # GitHub access
OPENROUTER_API_KEY    # Alternative LLM
```

### Optional

```env
JIRA_PROJECT_KEY=PROJ           # Default: ST
JIRA_EXCLUDED_TICKET_KEYS=KEY1,KEY2
GITHUB_REPO=owner/repo
GITHUB_BASE_BRANCH=main
TARGET_REPO_PATH=/path/to/repo
TARGET_REPO_ID=repo-id
FRONTEND_CORS_ORIGINS=...
```

### NOT NEEDED Anymore

```env
# ❌ No longer used - remove from .env
REPOS_BASE_DIR=...
```

---

## Development

### Make changes to backend

1. Backend auto-reloads with `--reload` flag
2. Check logs for errors
3. Test with Swagger UI: `http://localhost:8000/docs`

### Make changes to frontend

1. Frontend auto-reloads on file save
2. Check browser console for errors
3. TypeScript errors shown in terminal

---

## API Testing

### Swagger UI
```
http://localhost:8000/docs
```

### Example: Clone a repository
```bash
curl -X POST http://localhost:8000/agent/clone-repo \
  -H "Content-Type: application/json" \
  -d '{
    "repoId": "my-repo",
    "repoUrl": "https://github.com/owner/repo.git",
    "ref": "main",
    "localStorageLocation": "./repos"
  }'
```

### Example: Get tickets
```bash
curl http://localhost:8000/tickets
```

---

## Next Steps

1. ✅ Configure `.env` with your API keys
2. ✅ Start backend (port 8000)
3. ✅ Start frontend (port 3000)
4. ✅ Open `http://localhost:3000`
5. ✅ Ingest a repository
6. ✅ Load incidents from Jira
7. ✅ Run the fix pipeline

---

## Support

- **Issues?** Check `ACTION_PLAN.txt` for detailed setup
- **Full docs?** See `README.md`
- **Code changes?** Look at `backend/app/config.py` and `backend/app/agents/github_clone_agent.py`

---

**All platforms supported. All ready to use. Happy fixing!** 🚀
