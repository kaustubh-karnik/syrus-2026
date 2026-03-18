const request = require("supertest");
const app = require("../src/index");
const { sequelize, User } = require("../src/models");

beforeAll(async () => {
  await sequelize.sync({ force: true });
});

afterAll(async () => {
  await sequelize.close();
});

beforeEach(async () => {
  await User.destroy({ where: {} });
});

describe("User Registration", () => {
  test("should register user with valid data", async () => {
    const res = await request(app)
      .post("/api/auth/register")
      .send({
        email: "test@example.com",
        password: "password123",
        name: "Test User",
      });

    expect(res.statusCode).toBe(201);
    expect(res.body.user.email).toBe("test@example.com");
    expect(res.body.token).toBeDefined();
  });

  test("should accept valid email with plus addressing", async () => {
    const res = await request(app)
      .post("/api/auth/register")
      .send({
        email: "user+tag@example.com",
        password: "password123",
        name: "Plus User",
      });

    expect(res.statusCode).toBe(201);
    expect(res.body.user.email).toBe("user+tag@example.com");
  });

  test("should accept valid email with dots", async () => {
    const res = await request(app)
      .post("/api/auth/register")
      .send({
        email: "first.middle.last@example.com",
        password: "password123",
        name: "Dot User",
      });

    expect(res.statusCode).toBe(201);
  });

  test("should reject registration without password", async () => {
    const res = await request(app)
      .post("/api/auth/register")
      .send({
        email: "test@example.com",
        name: "Test User",
      });

    expect(res.statusCode).toBe(400);
  });

  test("should reject duplicate email", async () => {
    // Register first user
    await request(app)
      .post("/api/auth/register")
      .send({
        email: "duplicate@example.com",
        password: "password123",
        name: "First User",
      });

    // Try to register with same email
    const res = await request(app)
      .post("/api/auth/register")
      .send({
        email: "duplicate@example.com",
        password: "password456",
        name: "Second User",
      });

    expect(res.statusCode).toBe(409);
  });
});

describe("User Login", () => {
  beforeEach(async () => {
    await request(app)
      .post("/api/auth/register")
      .send({
        email: "login@example.com",
        password: "password123",
        name: "Login User",
      });
  });

  test("should login with valid credentials", async () => {
    const res = await request(app)
      .post("/api/auth/login")
      .send({
        email: "login@example.com",
        password: "password123",
      });

    expect(res.statusCode).toBe(200);
    expect(res.body.token).toBeDefined();
  });

  test("should reject invalid password", async () => {
    const res = await request(app)
      .post("/api/auth/login")
      .send({
        email: "login@example.com",
        password: "wrongpassword",
      });

    expect(res.statusCode).toBe(401);
  });

  test("should reject non-existent email", async () => {
    const res = await request(app)
      .post("/api/auth/login")
      .send({
        email: "nonexistent@example.com",
        password: "password123",
      });

    expect(res.statusCode).toBe(401);
  });
});
