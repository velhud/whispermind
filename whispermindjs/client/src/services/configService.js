import axios from 'axios';

class ConfigService {
  async getConfig() {
    try {
      const response = await axios.get('/api/config');
      return response.data;
    } catch (error) {
      console.error('Error loading config:', error);
      throw error.response?.data || error;
    }
  }
  
  async updateConfig(config) {
    try {
      const response = await axios.post('/api/config', config);
      return response.data;
    } catch (error) {
      console.error('Error updating config:', error);
      throw error.response?.data || error;
    }
  }

  async clearHistory() {
    try {
      const response = await axios.delete('/api/history');
      return response.data;
    } catch (error) {
      console.error('Error clearing history:', error);
      throw error.response?.data || error;
    }
  }
}

export const configService = new ConfigService();
