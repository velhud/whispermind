const { configService } = require('../services/configService');

const configController = {
  async getConfig(req, res) {
    try {
      await configService.ensureReady();
      const config = configService.getConfig();
      res.json({ ...config, constants: configService.constants() });
    } catch (error) {
      console.error('Error getting config:', error);
      res.status(500).json({ error: error.message });
    }
  },
  
  async updateConfig(req, res) {
    try {
      const result = await configService.updateConfig(req.body);
      if (result.success) {
        res.json({ success: true, config: { ...configService.getConfig(), constants: configService.constants() } });
      } else {
        res.status(500).json({ error: result.error });
      }
    } catch (error) {
      console.error('Error updating config:', error);
      res.status(500).json({ error: error.message });
    }
  },
  
  async getProfiles(req, res) {
    try {
      const profiles = await configService.getProfiles();
      res.json({ profiles });
    } catch (error) {
      console.error('Error getting profiles:', error);
      res.status(500).json({ error: error.message });
    }
  },
  
  async saveProfile(req, res) {
    try {
      const { name, data } = req.body;
      const result = await configService.saveProfile(name, data);
      if (result.success) {
        res.json({ success: true, profileName: result.profileName });
      } else {
        res.status(500).json({ error: result.error });
      }
    } catch (error) {
      console.error('Error saving profile:', error);
      res.status(500).json({ error: error.message });
    }
  },
  
  async loadProfile(req, res) {
    try {
      const { name } = req.params;
      const result = await configService.loadProfile(name);
      if (result.success) {
        res.json({ success: true, config: { ...result.config, constants: configService.constants() } });
      } else {
        res.status(500).json({ error: result.error });
      }
    } catch (error) {
      console.error('Error loading profile:', error);
      res.status(500).json({ error: error.message });
    }
  }
};

module.exports = { configController };
