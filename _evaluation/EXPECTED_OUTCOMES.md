# Expected Outcomes Per Incident

> **CONFIDENTIAL** — For judges only. Do not share with participants.

---

## Python Service Incidents

### INC-001: Login 500 Error (Runtime Crash)
**Difficulty**: Easy

**Root Cause**: In `app/routes/auth.py:46`, `bcrypt.checkpw()` receives `user.password_hash` as a `str`, but it requires `bytes`. The password hash is stored as a decoded string (line 27: `.decode("utf-8")`), so it must be re-encoded when checking.

**Expected Fix**:
```python
# Line 46 in app/routes/auth.py
# Before:
is_valid = bcrypt.checkpw(data["password"].encode("utf-8"), user.password_hash)
# After:
is_valid = bcrypt.checkpw(data["password"].encode("utf-8"), user.password_hash.encode("utf-8"))
```

**Validation**: `test_login_success` and `test_login_wrong_password` in `tests/test_auth.py` should pass.

**Tests That Should Pass After Fix**: `TestLogin::test_login_success`, `TestLogin::test_login_wrong_password`

---

### INC-002: DB Connection Failure in Staging (Misconfiguration)
**Difficulty**: Medium

**Root Cause**: In `app/config.py`, `StagingConfig` and `ProductionConfig` read env vars `DB_HOST`, `DB_USER`, `DB_PASS`, `DB_PORT`, `DB_NAME` — but `docker-compose.yml` and `.env.example` set `DATABASE_HOST`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_PORT`, `DATABASE_NAME`. The env var names don't match.

**Expected Fix**: Update `StagingConfig` and `ProductionConfig` in `app/config.py` to use the correct env var names:
```python
class StagingConfig(BaseConfig):
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://"
        f"{os.environ.get('DATABASE_USER', 'appuser')}:"
        f"{os.environ.get('DATABASE_PASSWORD', 'apppassword')}@"
        f"{os.environ.get('DATABASE_HOST', 'localhost')}:"
        f"{os.environ.get('DATABASE_PORT', '5432')}/"
        f"{os.environ.get('DATABASE_NAME', 'ecommerce')}"
    )
```

**Validation**: Service connects to database when deployed with docker-compose.

---

### INC-003: ImportError After Flask Upgrade (Dependency Issue)
**Difficulty**: Medium

**Root Cause**: `app/__init__.py:7` imports `from flask.json import JSONEncoder`, which was removed in Flask 2.3+. The `CustomJSONEncoder` subclass and `app.json_encoder` assignment are both broken.

**Expected Fix**: Replace with Flask 2.3+ JSON provider pattern:
```python
from flask.json.provider import DefaultJSONProvider

class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

# In create_app():
app.json_provider_class = CustomJSONProvider
app.json = CustomJSONProvider(app)
```

**Validation**: Application starts without ImportError. JSON responses correctly serialize datetime and Decimal.

---

### INC-004: Tax Calculation Bug (Test Failure)
**Difficulty**: Easy

**Root Cause**: In `app/services/payment_service.py:22`, `calculate_tax()` uses integer division `//` instead of float division `/`:
```python
tax = int(subtotal) // 100 * TAX_RATE  # BUG: integer division
```
For subtotals < 100: `int(49.99) // 100 = 0`, so tax = 0.

**Expected Fix**:
```python
tax = subtotal * TAX_RATE / 100
# or equivalently:
tax = subtotal * 0.085
```

**Validation**: `test_calculate_tax_small_amount`, `test_calculate_tax_large_amount`, `test_calculate_total_with_tax`, and `test_checkout_flow_complete` should pass.

---

### INC-005: Slow /orders Endpoint (Performance / N+1 Query)
**Difficulty**: Hard

**Root Cause**: In `app/routes/orders.py:19-30`, `list_orders()` fires individual SQL queries for each order's items and each item's product. With 50 orders of 5 items each, this generates 1 + 50 + 250 = 301 queries.

**Expected Fix**: Use eager loading (joinedload or subqueryload):
```python
from sqlalchemy.orm import joinedload

orders = Order.query.filter_by(user_id=int(user_id))\
    .options(joinedload(Order.items).joinedload(OrderItem.product))\
    .all()

result = [order.to_dict(include_items=True) for order in orders]
```

**Validation**: Should generate 1-3 SQL queries instead of 301. Response time should drop from seconds to milliseconds.

---

### INC-006: Double Discount (Logic Bug)
**Difficulty**: Medium

**Root Cause**: `apply_discount()` is called in TWO places:
1. `app/routes/payments.py:30` — in the `/calculate` preview endpoint
2. `app/routes/orders.py:66` — in the order creation endpoint

When a user calls `/calculate` first and then creates an order, the discount concept is applied twice in the order creation flow. Specifically, in `orders.py:66`, `apply_discount()` returns a reduced subtotal AND a discount_amount — but then line 68 subtracts discount_amount AGAIN: `total = subtotal + tax - discount_amount`. Since `subtotal` is already reduced, this double-subtracts.

**Expected Fix**: Either:
1. Don't modify subtotal in apply_discount — only return the discount amount
2. Or don't subtract discount_amount again when calculating total

```python
# Option 1: Fix in orders.py
if discount_code:
    _, discount_amount = apply_discount(subtotal, discount_code)
total = subtotal + tax - discount_amount  # subtotal is original, discount applied once
```

**Validation**: $100 order with SAVE20 should total $80 + tax, not $64 + tax.

---

### INC-007: SQL Injection (Security)
**Difficulty**: Easy-Medium

**Root Cause**: `app/routes/products.py:55`, the search query is directly interpolated into raw SQL via f-string:
```python
sql = f"SELECT * FROM products WHERE name LIKE '%{query}%'..."
```

**Expected Fix**: Use parameterized queries:
```python
sql = "SELECT * FROM products WHERE name LIKE :query OR description LIKE :query"
results = db.session.execute(db.text(sql), {"query": f"%{query}%"})
```
Or better, use SQLAlchemy ORM:
```python
results = Product.query.filter(
    db.or_(Product.name.ilike(f"%{query}%"), Product.description.ilike(f"%{query}%"))
).all()
```

**Validation**: `test_search_sql_injection_prevention` and `test_search_with_union_select` should pass.

---

### INC-008: Checkout Crash — Missing Import (Missing Import)
**Difficulty**: Easy

**Root Cause**: In `app/routes/payments.py:62`, `logging.info(...)` is called but the `logging` module is never imported at the top of the file. The app starts fine (the function isn't called at import time), but the checkout endpoint crashes with `NameError: name 'logging' is not defined` when processing a payment.

**Expected Fix**: Add `import logging` at the top of `app/routes/payments.py`:
```python
import logging
```

**Validation**: `test_checkout_processes_payment` in `tests/test_payments.py` should pass — the order status should change to "paid".

**Tests That Should Pass After Fix**: `TestCheckout::test_checkout_processes_payment`

---

## Node.js Service Incidents

### INC-101: Unhandled Promise Rejection (Runtime Crash)
**Difficulty**: Easy

**Root Cause**: `src/routes/users.js:14-16`, the `GET /:id` route handler is `async` but doesn't have a try/catch block. When `userService.getById()` throws (user not found), it becomes an unhandled promise rejection.

**Expected Fix**:
```javascript
router.get("/:id", authenticate, async (req, res) => {
  try {
    const user = await userService.getById(req.params.id);
    res.json({ user: user.toJSON() });
  } catch (error) {
    if (error.message === "User not found") {
      return res.status(404).json({ error: "User not found" });
    }
    res.status(500).json({ error: "Internal server error" });
  }
});
```

**Validation**: `test should return 404 for non-existent user` should pass without crashing.

---

### INC-102: CORS Misconfiguration
**Difficulty**: Easy

**Root Cause**: `src/index.js:12`, CORS origin is set to `http://localhost:3000` (API's own origin). Frontend runs on port 5173 (Vite).

**Expected Fix**:
```javascript
app.use(cors({
  origin: ["http://localhost:5173", "http://localhost:3000"],
  credentials: true,
}));
```
Or use an env variable for configurable origins.

**Validation**: Frontend requests from port 5173 should not be blocked.

---

### INC-103: express-validator v7 Breaking Change (Dependency Issue)
**Difficulty**: Hard

**Root Cause**: `src/middleware/validate.js` uses express-validator v6 API (`check()`, `validationResult()` patterns) but `package.json` has `express-validator ^7.0.1`. In v7, the API changed significantly — `check()` was replaced with `body()`, `query()`, etc., and the way validation runs changed.

**Expected Fix**: Update to v7 API:
```javascript
const { body, validationResult } = require("express-validator");

const registerValidation = [
  body("email").isEmail().withMessage("Invalid email format"),
  body("password").isLength({ min: 8 }).withMessage("Password must be at least 8 characters"),
  body("name").notEmpty().withMessage("Name is required"),
];
```
Note: In v7, `check` still exists as an alias, so the actual breakage is more nuanced. The real issue might be that `validationResult` behavior changed or that the validation chain execution model changed.

**Validation**: POST /api/auth/register with empty body should return 400 with validation errors, not 500.

---

### INC-104: Email Validation Regex (Test Failure)
**Difficulty**: Easy

**Root Cause**: `src/middleware/validate.js:11`, the custom `EMAIL_REGEX` doesn't allow `+` in the local part:
```javascript
const EMAIL_REGEX = /^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
```
The `+` character is missing from the character class.

**Expected Fix**:
```javascript
const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
```
Or remove the custom regex and rely on express-validator's built-in `isEmail()`.

**Validation**: `test should accept valid email with plus addressing` should pass.

---

### INC-105: Synchronous File Read Blocking Event Loop (Performance)
**Difficulty**: Medium

**Root Cause**: `src/routes/reports.js:22`, `fs.readFileSync()` is called on every request to the `/sales` endpoint. This blocks the event loop while reading the file.

**Expected Fix**: Either cache the template at startup or use async file read:
```javascript
// Option 1: Cache at startup
const template = fs.readFileSync(TEMPLATE_PATH, "utf-8"); // Read once at module load
// Then clone/use the cached string in the route handler

// Option 2: Async read
const template = await fs.promises.readFile(TEMPLATE_PATH, "utf-8");
```

**Validation**: Other endpoints should respond normally while report is being generated.

---

### INC-106: Pagination Off-by-One (Logic Bug)
**Difficulty**: Easy

**Root Cause**: `src/utils/formatters.js:41`, offset calculation uses `page * limit` instead of `(page - 1) * limit`:
```javascript
const offset = parsedPage * parsedLimit; // Should be (parsedPage - 1) * parsedLimit
```

**Expected Fix**:
```javascript
const offset = (parsedPage - 1) * parsedLimit;
```

**Validation**: `test page 1 should have offset 0` and `test should return first page correctly` should pass.

---

### INC-107: Null Reference in User Profile (Type Error)
**Difficulty**: Easy

**Root Cause**: `src/utils/formatters.js:14-15`, accesses `user.profile.avatar` and `user.profile.bio` without checking if `user.profile` is null/undefined.

**Expected Fix**:
```javascript
avatar: user.profile?.avatar ?? null,
bio: user.profile?.bio ?? null,
```

**Validation**: `test should handle user without profile (null profile)` and `test should handle user with undefined profile` should pass.

---

### INC-108: Product Search Crash — Missing Dependency (Missing Dependency)
**Difficulty**: Easy-Medium

**Root Cause**: `src/routes/products.js` has a `/search` endpoint that calls `require("fuse.js")` inside the handler function. The `fuse.js` package is NOT listed in `package.json` and is not installed. The app starts fine (the require is lazy, inside a function), but calling `GET /api/products/search?q=...` crashes with `Cannot find module 'fuse.js'`.

**Expected Fix**: Replace the fuse.js dependency with Sequelize's built-in `Op.like` operator (already available via Sequelize):
```javascript
const { Op } = require("sequelize");
const products = await Product.findAll({
  where: {
    [Op.or]: [
      { name: { [Op.like]: `%${q}%` } },
      { description: { [Op.like]: `%${q}%` } },
    ],
  },
});
res.json({ products: products.map(formatProductResponse), count: products.length });
```

Alternative fix: Install fuse.js (`npm install fuse.js`) and add it to package.json. Both approaches are acceptable.

**Validation**: `test should search products by name` in `tests/products.test.js` should pass.

**Tests That Should Pass After Fix**: `GET /api/products/search > should search products by name`

---

## Summary: Test Results Before/After

### Before Fixes (Expected Failures)
**Python**: All tests blocked by INC-003 ImportError; after fixing INC-003, additional failures from INC-001, INC-004, INC-006, INC-007, INC-008
**Node.js**: ~11 test failures across auth, users, products, formatters

### After All Fixes
**Python**: All tests pass (0 failures)
**Node.js**: All tests pass (0 failures)
