# Next.js Ticket-to-Fix Frontend

This frontend provides a production-style web control center for autonomous ticket remediation workflows.

## Features

- Mission-control style onboarding with repository preview and staged clone progress
- Jira ticket queue panel with ticket drafting (severity, assignee, keyword detection)
- Pipeline stepper with live terminal log stream (`POST /pipeline/solve-all-bugs`)
- Patch perspective "Code Diff Viewer" built from run artifacts
- Structured resolution report with copy/export actions (`GET /pipeline/last-run`)
- Backend URL sourced from shared environment (`NEXT_PUBLIC_BACKEND_BASE_URL`)

## Environment setup

Use the shared repository `.env` file at the project root:

```env
NEXT_PUBLIC_BACKEND_BASE_URL=http://127.0.0.1:8000
```

## Run

1. Start backend FastAPI server.
2. Ensure `NEXT_PUBLIC_BACKEND_BASE_URL` is present in the shared root `.env`.
3. Install dependencies in this folder.
4. Start Next.js dev server.

The app opens at `http://localhost:3000`.
