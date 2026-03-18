const { formatUserResponse, formatProductResponse, paginate } = require("../src/utils/formatters");

describe("paginate", () => {
  test("page 1 should have offset 0", () => {
    const result = paginate(1, 10);
    expect(result.offset).toBe(0);
    expect(result.limit).toBe(10);
    expect(result.page).toBe(1);
  });

  test("page 2 should have offset equal to limit", () => {
    const result = paginate(2, 10);
    expect(result.offset).toBe(10);
    expect(result.limit).toBe(10);
  });

  test("page 3 with limit 5 should have offset 10", () => {
    const result = paginate(3, 5);
    expect(result.offset).toBe(10);
    expect(result.limit).toBe(5);
  });

  test("should default to page 1 and limit 10", () => {
    const result = paginate(undefined, undefined);
    expect(result.page).toBe(1);
    expect(result.limit).toBe(10);
    expect(result.offset).toBe(0);
  });
});

describe("formatUserResponse", () => {
  test("should format user with profile", () => {
    const user = {
      id: 1,
      email: "test@example.com",
      name: "Test User",
      role: "customer",
      profile: { avatar: "https://example.com/avatar.jpg", bio: "Hello" },
      createdAt: new Date("2024-01-01"),
    };

    const result = formatUserResponse(user);
    expect(result.avatar).toBe("https://example.com/avatar.jpg");
    expect(result.bio).toBe("Hello");
  });

  test("should handle user without profile (null profile)", () => {
    const user = {
      id: 2,
      email: "new@example.com",
      name: "New User",
      role: "customer",
      profile: null,
      createdAt: new Date("2024-01-01"),
    };

    const result = formatUserResponse(user);
    expect(result.avatar).toBeNull();
    expect(result.bio).toBeNull();
  });

  test("should handle user with undefined profile", () => {
    const user = {
      id: 3,
      email: "undefined@example.com",
      name: "Undefined User",
      role: "customer",
      createdAt: new Date("2024-01-01"),
    };

    const result = formatUserResponse(user);
    expect(result.avatar).toBeNull();
  });
});

describe("formatProductResponse", () => {
  test("should format product correctly", () => {
    const product = {
      id: 1,
      name: "Widget",
      description: "A widget",
      price: "29.99",
      stock: 100,
      category: "widgets",
      createdAt: new Date("2024-01-01"),
    };

    const result = formatProductResponse(product);
    expect(result.price).toBe(29.99);
    expect(typeof result.price).toBe("number");
  });
});
