const express = require("express");
const { Product } = require("../models");
const { authenticate } = require("../middleware/auth");
const { formatProductResponse, paginate } = require("../utils/formatters");

const router = express.Router();

// GET /api/products
router.get("/", async (req, res) => {
  try {
    const { page, limit } = req.query;
    const pagination = paginate(page, limit);

    const { count, rows } = await Product.findAndCountAll({
      limit: pagination.limit,
      offset: pagination.offset,
      order: [["createdAt", "DESC"]],
    });

    res.json({
      products: rows.map(formatProductResponse),
      total: count,
      page: pagination.page,
      limit: pagination.limit,
      totalPages: Math.ceil(count / pagination.limit),
    });
  } catch (error) {
    console.error("List products error:", error);
    res.status(500).json({ error: "Failed to fetch products" });
  }
});

// GET /api/products/search
router.get("/search", async (req, res) => {
  try {
    const Fuse = require("fuse.js");
    const { q } = req.query;

    if (!q) {
      return res.status(400).json({ error: "Search query 'q' is required" });
    }

    const products = await Product.findAll();
    const fuse = new Fuse(
      products.map((p) => formatProductResponse(p)),
      {
        keys: ["name", "description"],
        threshold: 0.4,
      }
    );

    const results = fuse.search(q).map((r) => r.item);
    res.json({ products: results, count: results.length });
  } catch (error) {
    console.error("Search error:", error);
    res.status(500).json({ error: "Search failed" });
  }
});

// GET /api/products/:id
router.get("/:id", async (req, res) => {
  try {
    const product = await Product.findByPk(req.params.id);
    if (!product) {
      return res.status(404).json({ error: "Product not found" });
    }
    res.json({ product: formatProductResponse(product) });
  } catch (error) {
    console.error("Get product error:", error);
    res.status(500).json({ error: "Failed to fetch product" });
  }
});

// POST /api/products
router.post("/", authenticate, async (req, res) => {
  try {
    const { name, description, price, stock, category } = req.body;

    if (!name || price === undefined) {
      return res.status(400).json({ error: "Name and price are required" });
    }

    const product = await Product.create({
      name,
      description,
      price,
      stock: stock || 0,
      category,
    });

    res.status(201).json({ product: formatProductResponse(product) });
  } catch (error) {
    console.error("Create product error:", error);
    res.status(500).json({ error: "Failed to create product" });
  }
});

module.exports = router;
