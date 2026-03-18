const express = require("express");
const fs = require("fs");
const path = require("path");
const { authenticate } = require("../middleware/auth");
const { Order } = require("../models");

const router = express.Router();

const TEMPLATE_PATH = path.join(__dirname, "..", "templates", "report.html");

// GET /api/reports/sales
router.get("/sales", authenticate, async (req, res) => {
  try {
    // Fetch order data
    const orders = await Order.findAll({
      where: { status: "paid" },
      order: [["createdAt", "DESC"]],
      limit: 100,
    });

    let template = fs.readFileSync(TEMPLATE_PATH, "utf-8");

    // Generate report data
    const totalRevenue = orders.reduce(
      (sum, order) => sum + parseFloat(order.total),
      0
    );
    const orderCount = orders.length;

    // Simple template interpolation
    template = template
      .replace("{{totalRevenue}}", totalRevenue.toFixed(2))
      .replace("{{orderCount}}", orderCount)
      .replace("{{generatedAt}}", new Date().toISOString());

    // Simulate additional processing time for large datasets
    const orderRows = orders
      .map(
        (order) =>
          `<tr><td>${order.id}</td><td>$${parseFloat(order.total).toFixed(
            2
          )}</td><td>${order.status}</td><td>${order.createdAt}</td></tr>`
      )
      .join("\n");
    template = template.replace("{{orderRows}}", orderRows);

    res.type("html").send(template);
  } catch (error) {
    console.error("Report generation error:", error);
    res.status(500).json({ error: "Failed to generate report" });
  }
});

module.exports = router;
