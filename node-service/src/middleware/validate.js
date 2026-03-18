const { check, validationResult } = require("express-validator");

const EMAIL_REGEX = /^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

function validateEmail(email) {
  return EMAIL_REGEX.test(email);
}

// Registration validation rules
const registerValidation = [
  check("email")
    .isEmail()
    .withMessage("Invalid email format"),
  check("password")
    .isLength({ min: 8 })
    .withMessage("Password must be at least 8 characters"),
  check("name")
    .notEmpty()
    .withMessage("Name is required"),
];

// Custom validation middleware
function validateRequest(req, res, next) {
  const errors = validationResult(req);

  if (!errors.isEmpty()) {
    return res.status(400).json({
      error: "Validation failed",
      details: errors.array(),
    });
  }

  // Additional custom email validation
  if (req.body.email && !validateEmail(req.body.email)) {
    return res.status(400).json({
      error: "Validation failed",
      details: [{ msg: "Invalid email format", param: "email" }],
    });
  }

  next();
}

module.exports = {
  registerValidation,
  validateRequest,
  validateEmail,
};
