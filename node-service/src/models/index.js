const { Sequelize, DataTypes } = require("sequelize");
const config = require("../config");

let sequelize;

if (process.env.NODE_ENV === "test") {
  sequelize = new Sequelize("sqlite::memory:", { logging: false });
} else {
  sequelize = new Sequelize(
    config.database.name,
    config.database.username,
    config.database.password,
    {
      host: config.database.host,
      port: config.database.port,
      dialect: config.database.dialect,
      logging: config.database.logging,
    }
  );
}

// User model
const User = sequelize.define("User", {
  id: {
    type: DataTypes.INTEGER,
    primaryKey: true,
    autoIncrement: true,
  },
  email: {
    type: DataTypes.STRING,
    allowNull: false,
    unique: true,
  },
  passwordHash: {
    type: DataTypes.STRING,
    allowNull: false,
    field: "password_hash",
  },
  name: {
    type: DataTypes.STRING,
    allowNull: false,
  },
  profile: {
    type: DataTypes.JSON,
    allowNull: true,
    defaultValue: null,
  },
  role: {
    type: DataTypes.STRING,
    defaultValue: "customer",
  },
});

// Product model
const Product = sequelize.define("Product", {
  id: {
    type: DataTypes.INTEGER,
    primaryKey: true,
    autoIncrement: true,
  },
  name: {
    type: DataTypes.STRING,
    allowNull: false,
  },
  description: {
    type: DataTypes.TEXT,
  },
  price: {
    type: DataTypes.DECIMAL(10, 2),
    allowNull: false,
  },
  stock: {
    type: DataTypes.INTEGER,
    defaultValue: 0,
  },
  category: {
    type: DataTypes.STRING,
  },
});

// Order model
const Order = sequelize.define("Order", {
  id: {
    type: DataTypes.INTEGER,
    primaryKey: true,
    autoIncrement: true,
  },
  status: {
    type: DataTypes.STRING,
    defaultValue: "pending",
  },
  subtotal: {
    type: DataTypes.DECIMAL(10, 2),
    allowNull: false,
  },
  tax: {
    type: DataTypes.DECIMAL(10, 2),
    defaultValue: 0,
  },
  total: {
    type: DataTypes.DECIMAL(10, 2),
    allowNull: false,
  },
});

// Associations
User.hasMany(Order, { foreignKey: "userId" });
Order.belongsTo(User, { foreignKey: "userId" });

module.exports = {
  sequelize,
  User,
  Product,
  Order,
};
