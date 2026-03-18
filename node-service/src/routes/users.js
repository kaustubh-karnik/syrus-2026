const express = require("express");
const { authenticate } = require("../middleware/auth");
const userService = require("../services/userService");
const { formatUserResponse } = require("../utils/formatters");

const router = express.Router();

// GET /api/users/:id
router.get("/:id", authenticate, async (req, res) => {
  const user = await userService.getById(req.params.id);
  res.json({ user: user.toJSON() });
});

// GET /api/users/me/profile
router.get("/me/profile", authenticate, async (req, res) => {
  try {
    const user = await userService.getById(req.userId);
    const formatted = formatUserResponse(user);
    res.json({ user: formatted });
  } catch (error) {
    console.error("Profile error:", error);
    res.status(500).json({ error: "Failed to fetch profile" });
  }
});

// PUT /api/users/me/profile
router.put("/me/profile", authenticate, async (req, res) => {
  try {
    const { avatar, bio, phone } = req.body;
    const user = await userService.updateProfile(req.userId, {
      avatar,
      bio,
      phone,
    });
    res.json({
      message: "Profile updated successfully",
      user: user.toJSON(),
    });
  } catch (error) {
    console.error("Profile update error:", error);
    res.status(500).json({ error: "Failed to update profile" });
  }
});

module.exports = router;
