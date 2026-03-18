const request = require("supertest");
const app = require("../src/index");
const { sequelize, User } = require("../src/models");

let authToken;
let testUserId;

beforeAll(async () => {
  await sequelize.sync({ force: true });

  // Register a test user
  const res = await request(app)
    .post("/api/auth/register")
    .send({
      email: "usertest@example.com",
      password: "password123",
      name: "User Test",
    });

  authToken = res.body.token;
  testUserId = res.body.user.id;
});

afterAll(async () => {
  await sequelize.close();
});

describe("GET /api/users/:id", () => {
  test("should return user by ID", async () => {
    const res = await request(app)
      .get(`/api/users/${testUserId}`)
      .set("Authorization", `Bearer ${authToken}`);

    expect(res.statusCode).toBe(200);
    expect(res.body.user.email).toBe("usertest@example.com");
  });

  test("should return 404 for non-existent user", async () => {
    const res = await request(app)
      .get("/api/users/99999")
      .set("Authorization", `Bearer ${authToken}`);

    expect(res.statusCode).toBe(404);
    expect(res.body.error).toBeDefined();
  });
});

describe("GET /api/users/me/profile", () => {
  test("should return profile for user without profile data", async () => {
    const res = await request(app)
      .get("/api/users/me/profile")
      .set("Authorization", `Bearer ${authToken}`);

    expect(res.statusCode).toBe(200);
    expect(res.body.user).toBeDefined();
    // Profile fields should be null/undefined for users without profiles
    expect(res.body.user.avatar).toBeNull();
  });

  test("should return profile after profile is set", async () => {
    // First, set the profile
    await request(app)
      .put("/api/users/me/profile")
      .set("Authorization", `Bearer ${authToken}`)
      .send({
        avatar: "https://example.com/avatar.jpg",
        bio: "Test bio",
        phone: "+1234567890",
      });

    // Then fetch it
    const res = await request(app)
      .get("/api/users/me/profile")
      .set("Authorization", `Bearer ${authToken}`);

    expect(res.statusCode).toBe(200);
    expect(res.body.user.avatar).toBe("https://example.com/avatar.jpg");
  });
});
