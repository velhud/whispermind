const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const cors = require('cors');
const dotenv = require('dotenv');
const path = require('path');
const multer = require('multer');

// Load environment variables before provider services are imported.
dotenv.config();

const { recordingController } = require('./controllers/recordingController');
const { transcriptionController } = require('./controllers/transcriptionController');
const { configController } = require('./controllers/configController');
const { configService } = require('./services/configService');
const { transcriptionService } = require('./services/transcriptionService');

// Initialize express app
const app = express();
const server = http.createServer(app);
const allowedOrigins = (process.env.CORS_ORIGIN || 'http://localhost:3000,http://127.0.0.1:3000,http://localhost:5000,http://127.0.0.1:5000,http://localhost:5010,http://127.0.0.1:5010')
  .split(',')
  .map((origin) => origin.trim())
  .filter(Boolean);

const corsOptions = {
  origin(origin, callback) {
    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, true);
      return;
    }
    callback(new Error(`Origin not allowed: ${origin}`));
  },
};

const io = socketIo(server, {
  cors: {
    origin: allowedOrigins,
    methods: ["GET", "POST"]
  }
});

// Middleware
app.use(cors(corsOptions));
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'client', 'build')));

// Set up multer for file uploads
const storage = multer.memoryStorage();
const upload = multer({
  storage,
  limits: {
    fileSize: 50 * 1024 * 1024,
    files: 1,
  },
  fileFilter(req, file, callback) {
    if (!file.mimetype.startsWith('audio/')) {
      callback(new Error('Only audio uploads are supported'));
      return;
    }
    callback(null, true);
  },
});

// WebSocket connection
io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);
  
  // Handle audio data streaming
  socket.on('audioData', (data) => {
    recordingController.processAudioChunk(data, socket);
  });
  
  // Handle recording start/stop
  socket.on('startRecording', () => {
    recordingController.startRecording(socket);
  });
  
  socket.on('stopRecording', () => {
    recordingController.stopRecording(socket);
  });

  socket.on('clearHistory', () => {
    transcriptionService.clearHistory();
    socket.emit('status', { message: 'Cleared transcript and suggestion history', type: 'info' });
  });
  
  // Handle disconnection
  socket.on('disconnect', () => {
    recordingController.clearSession(socket);
    console.log('Client disconnected:', socket.id);
  });
});

// API Routes
app.get('/api/health', (req, res) => {
  res.json({ ok: true });
});
app.post('/api/transcribe-file', upload.single('file'), transcriptionController.transcribeFile);
app.post('/api/generate-suggestions', transcriptionController.generateSuggestions);
app.delete('/api/history', (req, res) => {
  transcriptionService.clearHistory();
  res.json({ success: true });
});
app.get('/api/config', configController.getConfig);
app.post('/api/config', configController.updateConfig);
app.get('/api/profiles', configController.getProfiles);
app.post('/api/profiles', configController.saveProfile);
app.get('/api/profiles/:name', configController.loadProfile);

// Serve React app
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '..', 'client', 'build', 'index.html'));
});

// Start server
const PORT = process.env.PORT || 5000;
async function start() {
  await configService.initialize();
  transcriptionService.initialize();
  server.listen(PORT, '127.0.0.1', () => {
    console.log(`Server running on http://127.0.0.1:${PORT}`);
  });
}

if (require.main === module) {
  start().catch((error) => {
    console.error('Failed to start server:', error);
    process.exit(1);
  });
}

module.exports = { app, server, io, start };
