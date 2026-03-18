require("dotenv").config();

module.exports = {
  database: {
    host: process.env.DB_HOST || "localhost",
    port: parseInt(process.env.DB_PORT || "5432", 10),
    username: process.env.DB_USER || "appuser",
    password: process.env.DB_PASSWORD || "apppassword",
    name: process.env.DB_NAME || "ecommerce",
    dialect: "postgres",
    logging: process.env.NODE_ENV === "development" ? console.log : false,
  },
  jwt: {
    secret: process.env.JWT_SECRET || "dev-secret-key",
    expiresIn: "24h",
  },
  server: {
    port: parseInt(process.env.PORT || "3000", 10),
    env: process.env.NODE_ENV || "development",
  },
};
