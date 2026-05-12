import axios from 'axios';

class ProfileService {
  async getProfiles() {
    try {
      const response = await axios.get('/api/profiles');
      return response.data.profiles;
    } catch (error) {
      console.error('Error loading profiles:', error);
      throw error.response?.data || error;
    }
  }
  
  async saveProfile(name, data) {
    try {
      const response = await axios.post('/api/profiles', { name, data });
      return response.data;
    } catch (error) {
      console.error('Error saving profile:', error);
      throw error.response?.data || error;
    }
  }
  
  async loadProfile(name) {
    try {
      const response = await axios.get(`/api/profiles/${name}`);
      return response.data;
    } catch (error) {
      console.error('Error loading profile:', error);
      throw error.response?.data || error;
    }
  }
}

export const profileService = new ProfileService();