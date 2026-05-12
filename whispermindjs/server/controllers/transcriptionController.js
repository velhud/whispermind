const { transcriptionService } = require('../services/transcriptionService');
const { audioService } = require('../services/audioService');

const transcriptionController = {
  async transcribeFile(req, res) {
    try {
      if (!req.file) {
        return res.status(400).json({ error: 'No file uploaded' });
      }
      
      // Process the file and get the audio buffer
      const audioBuffer = await audioService.processAudioFile(req.file.buffer);
      
      const result = await transcriptionService.processFile(audioBuffer, req.file.originalname);
      res.json(result);
    } catch (error) {
      console.error('Error transcribing file:', error);
      res.status(500).json({ error: error.message });
    }
  },
  
  async generateSuggestions(req, res) {
    try {
      const result = await transcriptionService.generateSuggestions();
      res.json(result);
    } catch (error) {
      console.error('Error generating suggestions:', error);
      res.status(500).json({ error: error.message });
    }
  }
};

module.exports = { transcriptionController };
