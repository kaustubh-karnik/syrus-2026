# AutoResolve AI — Hackathon Test Repository

Welcome to the evaluation repository for **PS-02: Autonomous Incident-to-Fix Engineering Agent**.

This repo contains two e-commerce microservices (Python Flask + Node.js Express) with **16 embedded incidents** across a wide range of bug categories — runtime crashes, misconfigurations, logic errors, security vulnerabilities, performance issues, missing imports, missing dependencies, and more.

Your goal is to build an autonomous agent that can parse incident tickets, analyze the codebase, identify root causes, apply fixes, and validate them — all without human intervention.

---

## Two READMEs, Two Audiences

### [`Readme_Participants.md`](./Readme_Participants.md)

**For your team.** This is the comprehensive guide covering:

- Full architecture and repository structure
- Setup instructions for both services
- How to run tests and interpret results
- Incident ticket format and overview of all 16 incidents
- The workflow your agent must follow (parse → analyze → fix → validate → report)
- Evaluation criteria and scoring dimensions
- API endpoint reference, Docker setup, and troubleshooting

**Read this first** to understand the problem space, evaluation criteria, and what's expected.

### [`Readme_Agent.md`](./Readme_Agent.md)

**For your agent.** This is what a normal repository README looks like — no mention of hackathons, intentional bugs, or evaluation. It contains:

- Project architecture and tech stack
- Repository structure
- Setup and installation steps
- How to run tests
- API endpoint reference
- Environment variables
- Troubleshooting tips

Feed this to your agent as the repo context. It should discover and fix the bugs on its own using the incident tickets in the `incidents/` directory, without being told that bugs are intentionally planted.

---

## Quick Start

```bash
# Python service
cd python-service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/ -v

# Node.js service
cd node-service
npm install
npm test
```

Tests will have failures — that's the point. Your agent needs to fix them.

---

Good luck!
