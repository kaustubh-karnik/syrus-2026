#!/bin/bash
# Quick verification that all expected bugs are present in the codebase.
# Run this to confirm the test repo has not been accidentally fixed.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Verifying embedded bugs..."
echo ""

PASS=0
FAIL=0

check_bug() {
    local id="$1"
    local file="$2"
    local pattern="$3"
    local description="$4"

    if grep -q "$pattern" "$REPO_DIR/$file" 2>/dev/null; then
        echo "[PRESENT] $id: $description"
        ((PASS++))
    else
        echo "[MISSING] $id: $description (in $file)"
        ((FAIL++))
    fi
}

# Python bugs
check_bug "INC-001" "python-service/app/routes/auth.py" "user.password_hash$" "bcrypt bytes vs string bug"
check_bug "INC-002" "python-service/app/config.py" "DB_HOST" "Wrong env var names in staging config"
check_bug "INC-003" "python-service/app/__init__.py" "from flask.json import JSONEncoder" "Removed Flask JSONEncoder import"
check_bug "INC-004" "python-service/app/services/payment_service.py" "int(subtotal) // 100" "Integer division in tax calc"
check_bug "INC-005" "python-service/app/routes/orders.py" "for item in order.items" "N+1 query in order listing"
check_bug "INC-006" "python-service/app/routes/orders.py" "apply_discount(subtotal, discount_code)" "Double discount application"
check_bug "INC-007" "python-service/app/routes/products.py" "f\"SELECT \* FROM products WHERE name LIKE '%{query}%'" "SQL injection in search"

check_bug "INC-008" "python-service/app/routes/payments.py" "logging.info" "Missing logging import in checkout"

# Node.js bugs
check_bug "INC-101" "node-service/src/routes/users.js" "const user = await userService.getById(req.params.id)" "Missing try/catch in async handler"
check_bug "INC-102" "node-service/src/index.js" "origin: \"http://localhost:3000\"" "Wrong CORS origin"
check_bug "INC-103" "node-service/src/middleware/validate.js" "check(" "express-validator v6 API with v7 package"
check_bug "INC-104" "node-service/src/middleware/validate.js" 'a-zA-Z0-9._-' "Restrictive email regex missing +"
check_bug "INC-105" "node-service/src/routes/reports.js" "fs.readFileSync" "Synchronous file read in handler"
check_bug "INC-106" "node-service/src/utils/formatters.js" "parsedPage \* parsedLimit" "Off-by-one pagination"
check_bug "INC-107" "node-service/src/utils/formatters.js" "user.profile.avatar" "Missing null check on profile"

check_bug "INC-108" "node-service/src/routes/products.js" 'require("fuse.js")' "Missing fuse.js dependency in search"

echo ""
echo "Results: $PASS present, $FAIL missing"
echo "Total expected: 16"
