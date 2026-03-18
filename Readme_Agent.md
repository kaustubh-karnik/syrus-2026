# E-Commerce Platform — Microservices API

A full-stack e-commerce platform built with two independent microservices: a **Python Flask** API and a **Node.js Express** API. Both services share a common domain model covering users, products, orders, and payments.

---

## Architecture

| Service | Tech Stack | Port | Database |
|---------|-----------|------|----------|
| **Python Service** | Flask, SQLAlchemy, Flask-JWT-Extended, bcrypt | 5000 | PostgreSQL (SQLite for tests) |
| **Node.js Service** | Express, Sequelize, jsonwebtoken, bcryptjs | 3000 | PostgreSQL (SQLite for tests) |

Both services connect to a shared PostgreSQL database and Redis instance when deployed via Docker. For local development and testing, each service uses an in-memory SQLite database.

---

## Repository Structure

```
├── docker-compose.yml              # Container orchestration
├── .gitignore
│
├── incidents/                      # Incident tickets (structured JSON)
│   ├── INC-001.json ... INC-008.json    # Python service incidents
│   └── INC-101.json ... INC-108.json    # Node.js service incidents
│
├── python-service/                 # Python Flask API
│   ├── app/
│   │   ├── __init__.py             #   App factory, extensions, JSON serialization
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
├── scripts/
│   └── run_all_tests.sh            #   Run test suites for both services
│
└── .github/workflows/
    └── ci.yml                      #   GitHub Actions CI pipeline
```

---

## Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Python | 3.10+ |
| pip | Latest |
| Node.js | 18+ |
| npm | 9+ |
| Docker & Docker Compose | 20+ / 2.0+ *(optional — only for full stack deployment)* |

---

## Setup

### Python Service

```bash
cd python-service

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Run the server (port 5000)
python run.py
```

### Node.js Service

```bash
cd node-service

# Install dependencies
npm install

# Run the server (port 3000)
npm start
```

### Docker (Full Stack)

```bash
docker-compose up --build

# Python API:  http://localhost:5000
# Node.js API: http://localhost:3000
# PostgreSQL:  localhost:5432
# Redis:       localhost:6379
```

---

## Running Tests

### Python Service
```bash
cd python-service
source venv/bin/activate
python -m pytest tests/ -v              # Run all tests
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

---

## Incident Tickets

The `incidents/` directory contains structured JSON incident tickets describing reported issues across both services. Each ticket includes:

- **id** — Unique identifier (e.g., `INC-001`)
- **title** — Short description of the issue
- **severity** — Priority level (P0–P3)
- **service** — Which service is affected
- **description** — Detailed description of the problem
- **steps_to_reproduce** — How to trigger the issue
- **error_log** — Relevant error messages or stack traces
- **expected_behavior** / **actual_behavior** — What should happen vs. what does happen
- **recent_changes** — What changed before the bug appeared
- **tags** — Categorization labels

---

## API Endpoints

### Python Service (port 5000)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register` | No | Register a new user |
| POST | `/api/auth/login` | No | Login and receive JWT token |
| GET | `/api/auth/me` | JWT | Get current user info |
| GET | `/api/products/` | No | List products (paginated) |
| GET | `/api/products/<id>` | No | Get product by ID |
| GET | `/api/products/search?q=` | No | Search products |
| POST | `/api/products/` | JWT | Create a product |
| GET | `/api/orders/` | JWT | List user's orders |
| GET | `/api/orders/<id>` | JWT | Get order by ID |
| POST | `/api/orders/` | JWT | Create an order |
| POST | `/api/payments/calculate` | JWT | Calculate total with tax/discount |
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
| GET | `/api/products/search?q=` | No | Search products |
| GET | `/api/products/:id` | No | Get product by ID |
| POST | `/api/products` | JWT | Create a product |
| GET | `/api/reports/sales` | JWT | Generate sales report |
| GET | `/api/health` | No | Health check |

---

## Environment Variables

### Python Service

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_HOST` | `localhost` | PostgreSQL host |
| `DATABASE_PORT` | `5432` | PostgreSQL port |
| `DATABASE_USER` | `appuser` | Database username |
| `DATABASE_PASSWORD` | `apppassword` | Database password |
| `DATABASE_NAME` | `ecommerce` | Database name |
| `SECRET_KEY` | `dev-secret-key` | Flask secret key |
| `FLASK_ENV` | `development` | Environment (`development`, `staging`, `production`) |

### Node.js Service

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_USER` | `appuser` | Database username |
| `DB_PASSWORD` | `apppassword` | Database password |
| `DB_NAME` | `ecommerce` | Database name |
| `JWT_SECRET` | `your-secret-key` | JWT signing secret |
| `PORT` | `3000` | Server port |
| `NODE_ENV` | `development` | Environment |

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `psycopg2-binary` fails to install | Skip it — tests use SQLite, not PostgreSQL |
| `ModuleNotFoundError: No module named 'app'` | Run commands from the `python-service/` directory |
| `sqlite3` build errors (Node) | Run `npm rebuild sqlite3` or ensure native build tools are installed |
| Port already in use | Set a different port: `PORT=3001 npm start` or `FLASK_RUN_PORT=5001 python run.py` |
