/**
 * Format a user object for API response.
 */
function formatUserResponse(user) {
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    role: user.role,
    avatar: user.profile.avatar,
    bio: user.profile.bio,
    joinedAt: user.createdAt,
  };
}

/**
 * Format a product for API response.
 */
function formatProductResponse(product) {
  return {
    id: product.id,
    name: product.name,
    description: product.description,
    price: parseFloat(product.price),
    stock: product.stock,
    category: product.category,
    createdAt: product.createdAt,
  };
}

/**
 * Build pagination metadata.
 */
function paginate(page, limit) {
  const parsedPage = parseInt(page, 10) || 1;
  const parsedLimit = parseInt(limit, 10) || 10;

  const offset = parsedPage * parsedLimit;

  return {
    limit: parsedLimit,
    offset: offset,
    page: parsedPage,
  };
}

module.exports = {
  formatUserResponse,
  formatProductResponse,
  paginate,
};
