#!/bin/bash
# Run all tests for both services and report results.
# This script is used to verify the test repository state.

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "============================================"
echo "  AutoResolve Test Repository - Test Runner"
echo "============================================"
echo ""

PYTHON_PASS=0
PYTHON_FAIL=0
NODE_PASS=0
NODE_FAIL=0

# --- Python Service Tests ---
echo ">>> Python Service Tests"
echo "------------------------"
cd "$REPO_DIR/python-service"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

# The app won't start due to INC-003 (ImportError), so we test selectively
echo "Running payment_service unit tests..."
python -m pytest tests/test_payments.py -v --tb=short 2>&1 || PYTHON_FAIL=1

echo ""
echo "Running product tests..."
python -m pytest tests/test_products.py -v --tb=short 2>&1 || PYTHON_FAIL=1

echo ""
echo "Running auth tests..."
python -m pytest tests/test_auth.py -v --tb=short 2>&1 || PYTHON_FAIL=1

echo ""
echo "Running order tests..."
python -m pytest tests/test_orders.py -v --tb=short 2>&1 || PYTHON_FAIL=1

echo ""
echo "Running security tests..."
python -m pytest tests/test_security.py -v --tb=short 2>&1 || PYTHON_FAIL=1

# --- Node.js Service Tests ---
echo ""
echo ">>> Node.js Service Tests"
echo "-------------------------"
cd "$REPO_DIR/node-service"

if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

echo "Running all Node.js tests..."
npm test 2>&1 || NODE_FAIL=1

# --- Summary ---
echo ""
echo "============================================"
echo "  Test Summary"
echo "============================================"
echo "Python Service: $([ $PYTHON_FAIL -eq 0 ] && echo 'ALL PASSED' || echo 'SOME FAILURES (expected)')"
echo "Node.js Service: $([ $NODE_FAIL -eq 0 ] && echo 'ALL PASSED' || echo 'SOME FAILURES (expected)')"
echo ""
echo "Note: Test failures are EXPECTED in this repository."
echo "The bugs in the code are intentional for hackathon evaluation."
