import axios from 'axios';

class SuggestionService {
  async generateSuggestions() {
    try {
      const response = await axios.post('/api/generate-suggestions');
      return response.data;
    } catch (error) {
      console.error('Error generating suggestions:', error);
      throw error.response?.data || error;
    }
  }
}

export const suggestionService = new SuggestionService();