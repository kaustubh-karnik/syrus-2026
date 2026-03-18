# AutoResolve AI - Hackathon Test Repository

This repository is the **evaluation environment** for the **AutoResolve AI Hackathon (PS-02: Autonomous Incident-to-Fix Engineering Agent)**. It contains two e-commerce microservices with **16 intentionally embedded bugs** that your autonomous agent must detect, diagnose, fix, and validate.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Running Tests](#running-tests)
- [Incident Tickets](#incident-tickets)
- [What Your Agent Must Do](#what-your-agent-must-do)
- [Evaluation Criteria](#evaluation-criteria)
- [API Endpoints Reference](#api-endpoints-reference)
- [Docker Setup (Optional)](#docker-setup-optional)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

The system consists of two independent microservices for an e-commerce platform:

| Service | Tech Stack | Port | Database |
|---------|-----------|------|----------|
| **Python Service** | Flask, SQLAlchemy, Flask-JWT-Extended, bcrypt | 5000 | PostgreSQL (SQLite for tests) |
| **Node.js Service** | Express, Sequelize, jsonwebtoken, bcryptjs | 3000 | PostgreSQL (SQLite for tests) |

Both services share a PostgreSQL database and Redis instance when deployed via Docker. For local development and testing, each service uses an in-memory SQLite database.

### Domain Model

Both services implement parts of the same e-commerce domain:

- **Users** — Registration, authentication (JWT), profiles
- **Products** — CRUD, search, pagination, categories
- **Orders** — Creation, listing, stock management, discount codes
- **Payments** — Tax calculation, checkout, payment processing

---

## Repository Structure

```
autoresolve-test-repo/
├── README.md                       # This file
├── docker-compose.yml              # Container orchestration (PostgreSQL, Redis, both services)
├── .env.example                    # Environment variable template
├── .gitignore
│
├── incidents/                      # Incident tickets (input for your agent)
│   ├── INC-001.json ... INC-008.json    # Python service incidents (8 tickets)
│   └── INC-101.json ... INC-108.json    # Node.js service incidents (8 tickets)
│
├── python-service/                 # Python Flask API
│   ├── app/
│   │   ├── __init__.py             #   App factory, extensions, JSON encoder
│   │   ├── config.py               #   Environment-based configuration
│   │   ├── models/                 #   SQLAlchemy models (User, Product, Order, OrderItem)
│   │   ├── routes/                 #   Blueprint route handlers (auth, products, orders, payments)
│   │   └── services/               #   Business logic (payment calculations)
│   ├── tests/                      #   Pytest test suite
│   │   ├── conftest.py             #   Fixtures (app, db, client, sample data, auth tokens)
│   │   ├── test_auth.py            #   Authentication tests
│   │   ├── test_orders.py          #   Order creation and listing tests
│   │   ├── test_payments.py        #   Tax, discount, and checkout tests
│   │   ├── test_products.py        #   Product CRUD and search tests
│   │   └── test_security.py        #   SQL injection prevention tests
│   ├── requirements.txt            #   Python dependencies
│   ├── Dockerfile
│   └── run.py                      #   Entry point
│
├── node-service/                   # Node.js Express API
│   ├── src/
│   │   ├── index.js                #   Express app setup, middleware, route mounting
│   │   ├── config.js               #   Configuration from environment variables
│   │   ├── models/                 #   Sequelize models (User, Product, Order, OrderItem)
│   │   ├── routes/                 #   Route handlers (auth, users, products, reports)
│   │   ├── middleware/             #   Auth (JWT), validation (express-validator)
│   │   ├── services/               #   Business logic (user service)
│   │   ├── utils/                  #   Formatters, pagination helpers
│   │   └── templates/              #   HTML templates (sales report)
│   ├── tests/                      #   Jest test suite
│   │   ├── auth.test.js            #   Registration and login tests
│   │   ├── users.test.js           #   User profile and fetch tests
│   │   ├── products.test.js        #   Product CRUD, pagination, and search tests
│   │   └── formatters.test.js      #   Unit tests for pagination and formatting utilities
│   ├── package.json                #   Node.js dependencies
│   ├── jest.config.js              #   Jest test configuration
│   └── Dockerfile
│
├── _evaluation/                    # FOR JUDGES ONLY (do not share with participants)
│   ├── EXPECTED_OUTCOMES.md        #   Root causes, expected fixes, validation per incident
│   └── SCORING_RUBRIC.md           #   Detailed scoring criteria
│
├── scripts/
│   ├── verify_bugs.sh              #   Verify all 16 bugs are present (grep-based)
│   └── run_all_tests.sh            #   Run test suites for both services
│
└── .github/workflows/
    └── ci.yml                      #   GitHub Actions CI pipeline
```

---

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| Python | 3.10+ | Python service runtime |
| pip | Latest | Python package manager |
| Node.js | 18+ | Node.js service runtime |
| npm | 9+ | Node.js package manager |
| Docker | 20+ *(optional)* | Containerized deployment |
| Docker Compose | 2.0+ *(optional)* | Multi-container orchestration |

> Docker is only needed if you want to run the full stack with PostgreSQL and Redis. Tests use in-memory SQLite and do **not** require Docker.

---

## Quick Start

### Python Service

```bash
cd python-service

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Run tests (some WILL fail — that's intentional)
python -m pytest tests/ -v

# Start the server (port 5000)
python run.py
```

> **Note:** You may see a `psycopg2-binary` installation error on some platforms. This is fine for testing since tests use SQLite. You can skip it and install the remaining packages individually.

### Node.js Service

```bash
cd node-service

# Install dependencies
npm install

# Run tests (some WILL fail — that's intentional)
npm test

# Start the server (port 3000)
npm start
```

---

## Running Tests

Tests are the primary validation mechanism. Your agent should use them to:
1. **Diagnose** which bugs exist (failing tests indicate bugs)
2. **Validate** that fixes work (previously failing tests should pass)
3. **Prevent regressions** (all other tests should continue passing)

### Python Service
```bash
cd python-service
source venv/bin/activate
python -m pytest tests/ -v              # Run all tests with verbose output
python -m pytest tests/test_auth.py -v  # Run specific test file
python -m pytest -x                     # Stop on first failure
```

### Node.js Service
```bash
cd node-service
npm test                                # Run all tests
npx jest tests/auth.test.js --verbose   # Run specific test file
npx jest --bail                         # Stop on first failure
```

> **Important:** Some tests are designed to fail. This is intentional — the bugs in the source code cause these failures. After applying correct fixes, **all tests should pass with 0 failures**.

---

## Incident Tickets

Each incident ticket is a JSON file in the `incidents/` directory. These are the inputs your agent will receive.

### Ticket Format

```json
{
  "id": "INC-001",
  "title": "Short description of the issue",
  "severity": "P1 - Critical",
  "service": "python-service",
  "reported_by": "Frontend Team",
  "environment": "staging",
  "timestamp": "2026-02-28T14:23:00Z",
  "description": "Detailed description of what's happening...",
  "steps_to_reproduce": ["Step 1", "Step 2", "Step 3"],
  "error_log": "Actual error message or stack trace",
  "expected_behavior": "What should happen",
  "actual_behavior": "What actually happens",
  "recent_changes": "What changed before the bug appeared",
  "tags": ["runtime-crash", "authentication", "blocking"]
}
```

### Incident Overview

| ID | Service | Category | Severity | Brief Description |
|----|---------|----------|----------|-------------------|
| INC-001 | Python | Runtime Crash | P1 | Login endpoint returns 500 |
| INC-002 | Python | Misconfiguration | P1 | Database connection fails in staging |
| INC-003 | Python | Incorrect Import | P2 | ImportError after Flask version upgrade |
| INC-004 | Python | Logic Bug | P2 | Tax calculation returns $0 for small orders |
| INC-005 | Python | Performance | P2 | Orders endpoint extremely slow (N+1 queries) |
| INC-006 | Python | Logic Bug | P1 | Discount applied twice, customers undercharged |
| INC-007 | Python | Security | P0 | SQL injection vulnerability in product search |
| INC-008 | Python | Missing Import | P1 | Checkout crashes with NameError |
| INC-101 | Node.js | Runtime Crash | P1 | Unhandled promise rejection crashes server |
| INC-102 | Node.js | Misconfiguration | P1 | CORS blocks frontend requests |
| INC-103 | Node.js | Dependency Mismatch | P2 | Validation broke after express-validator upgrade |
| INC-104 | Node.js | Logic Bug | P3 | Valid emails with `+` rejected |
| INC-105 | Node.js | Performance | P2 | Report endpoint blocks event loop |
| INC-106 | Node.js | Logic Bug | P2 | Pagination returns wrong results |
| INC-107 | Node.js | Type Error | P1 | Profile page crashes for users without profile |
| INC-108 | Node.js | Missing Dependency | P2 | Product search fails — module not found |

### Bug Categories Covered

- **Runtime Crashes** — Unhandled errors, type mismatches
- **Misconfigurations** — Wrong environment variables, CORS origins
- **Incorrect/Deprecated Imports** — Using removed APIs from upgraded packages
- **Missing Imports** — Using modules without importing them
- **Missing Dependencies** — Using packages not listed in dependency files
- **Dependency Version Mismatch** — Code written for old API running on new version
- **Logic Bugs** — Off-by-one errors, double-application of discounts
- **Performance Issues** — N+1 queries, blocking I/O in async contexts
- **Security Vulnerabilities** — SQL injection via string interpolation
- **Type Errors** — Null/undefined reference errors

---

## What Your Agent Must Do

For each incident ticket, your agent should follow this workflow:

### 1. Parse the Incident
Read and understand the incident ticket JSON. Extract the service name, error logs, reproduction steps, and tags.

### 2. Analyze the Codebase
Navigate the relevant service's source code. Use the error log and description to locate the root cause. Consider:
- The specific file and line mentioned in error logs
- Related files (models, services, middleware)
- Configuration files and dependency manifests
- Recent changes mentioned in the ticket

### 3. Diagnose the Root Cause
Identify the exact code defect. Your diagnosis should include:
- The file path and line number
- What the code does incorrectly
- Why it causes the reported behavior

### 4. Apply a Fix
Make the minimum necessary code change to resolve the issue. Fixes should be:
- **Correct** — Actually resolves the root cause, not just the symptom
- **Minimal** — Only changes what's necessary
- **Production-ready** — Follows existing code patterns and conventions

### 5. Validate the Fix
Run the test suite to confirm:
- Previously failing tests now pass
- No new test failures (no regressions)
- The fix works for edge cases

### 6. Generate a Resolution Report
Produce a structured report for each incident including:
- Root cause analysis
- Files modified and changes made
- Test results before and after
- Confidence score
- Risk assessment

---

## Evaluation Criteria

Your agent will be scored on these dimensions:

| Dimension | Weight | What's Evaluated |
|-----------|--------|-----------------|
| **Agent Intelligence** | 20% | Reasoning quality, handling ambiguous tickets, documentation research |
| **Fix Correctness & Validation** | 30% | Correct root cause, minimal fix, test quality, regression prevention |
| **System Architecture** | 15% | Modular design, sandboxed execution, scalability |
| **Resolution Reporting** | 15% | Clarity, completeness, confidence scoring, risk assessment |
| **Innovation & Impact** | 10% | Novel approaches, real-world applicability |
| **Bonus Integrations** | 10% | GitHub PR creation, Slack/Jira integration, branch management |

Each incident is scored 0-10 points across:
- Root Cause Identification (0-3)
- Fix Correctness (0-3)
- Test Validation (0-2)
- Resolution Report Quality (0-2)

---

## API Endpoints Reference

### Python Service (port 5000)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register` | No | Register a new user |
| POST | `/api/auth/login` | No | Login and receive JWT token |
| GET | `/api/auth/me` | JWT | Get current user info |
| GET | `/api/products/` | No | List products (paginated) |
| GET | `/api/products/<id>` | No | Get product by ID |
| GET | `/api/products/search?q=` | No | Search products by name/description |
| POST | `/api/products/` | JWT | Create a product |
| GET | `/api/orders/` | JWT | List user's orders |
| GET | `/api/orders/<id>` | JWT | Get order by ID |
| POST | `/api/orders/` | JWT | Create an order |
| POST | `/api/payments/calculate` | JWT | Calculate order total with tax/discount |
| POST | `/api/payments/checkout` | JWT | Process payment for an order |

### Node.js Service (port 3000)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register` | No | Register a new user |
| POST | `/api/auth/login` | No | Login and receive JWT token |
| GET | `/api/users/:id` | JWT | Get user by ID |
| GET | `/api/users/me/profile` | JWT | Get current user's profile |
| PUT | `/api/users/me/profile` | JWT | Update current user's profile |
| GET | `/api/products` | No | List products (paginated) |
| GET | `/api/products/search?q=` | No | Search products by name/description |
| GET | `/api/products/:id` | No | Get product by ID |
| POST | `/api/products` | JWT | Create a product |
| GET | `/api/reports/sales` | JWT | Generate sales report (HTML) |
| GET | `/api/health` | No | Health check |

---

## Docker Setup (Optional)

To run the full stack with PostgreSQL and Redis:

```bash
# Start all services
docker-compose up --build

# Services will be available at:
#   Python API:  http://localhost:5000
#   Node.js API: http://localhost:3000
#   PostgreSQL:  localhost:5432
#   Redis:       localhost:6379

# Stop all services
docker-compose down

# Stop and remove data volumes
docker-compose down -v
```

> **Note:** Docker is NOT required for testing. Tests use in-memory SQLite databases and run independently of Docker.

---

## Troubleshooting

### Python Service

| Issue | Solution |
|-------|----------|
| `psycopg2-binary` fails to install | Skip it — tests use SQLite, not PostgreSQL. |
| `ImportError` on app startup | This is an intentional bug (INC-003). Your agent should fix it. |
| All tests fail with `ImportError` | Same as above — INC-003 blocks the entire test suite from loading. |
| `ModuleNotFoundError: No module named 'app'` | Run commands from the `python-service/` directory. |

### Node.js Service

| Issue | Solution |
|-------|----------|
| `sqlite3` build errors | Run `npm rebuild sqlite3` or ensure native build tools are installed. |
| `Cannot find module 'sqlite3'` | Run `npm install sqlite3` — may need separate installation. |
| Tests hang or timeout | Some bugs cause unhandled promise rejections. This is intentional. |
| Port 3000 already in use | Set a different port: `PORT=3001 npm start` |

### General

| Issue | Solution |
|-------|----------|
| Tests pass that shouldn't | Ensure you're on the `master` branch with unmodified source code. |
| Need to reset to buggy state | Run `git checkout -- .` to discard all local changes. |

---

## For Judges

See `_evaluation/EXPECTED_OUTCOMES.md` for detailed root causes, expected fixes, and validation criteria per incident. See `_evaluation/SCORING_RUBRIC.md` for the scoring framework. Run `scripts/verify_bugs.sh` to confirm all 16 bugs are present.
