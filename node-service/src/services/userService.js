const { User } = require("../models");

class UserService {
  async getById(id) {
    const user = await User.findByPk(id);
    if (!user) {
      throw new Error("User not found");
    }
    return user;
  }

  async getByEmail(email) {
    return User.findOne({ where: { email } });
  }

  async create(data) {
    return User.create(data);
  }

  async updateProfile(id, profileData) {
    const user = await this.getById(id);
    user.profile = profileData;
    await user.save();
    return user;
  }
}

module.exports = new UserService();
