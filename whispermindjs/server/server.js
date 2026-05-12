const express = require('express');
const http = require('http');
const socketIo = require('socket.io');
const cors = require('cors');
const dotenv = require('dotenv');
const path = require('path');
const multer = require('multer');

// Load environment variables before provider services are imported.
// The JS UI can use its own server/.env, but also falls back to the project root
// .env used by the Tk app so both UIs share local credentials by default.
dotenv.config({ path: path.join(__dirname, '..', '..', '.env') });
dotenv.config({ path: path.join(__dirname, '.env'), override: true });

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
    const error = new Error(`Origin not allowed: ${origin}`);
    error.status = 403;
    callback(error);
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
      const error = new Error('Only audio uploads are supported');
      error.status = 400;
      callback(error);
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
    try {
      recordingController.processAudioChunk(data, socket);
    } catch (error) {
      socket.emit('status', { message: `Audio error: ${error.message}`, type: 'error' });
    }
  });
  
  // Handle recording start/stop
  socket.on('startRecording', (options = {}) => {
    try {
      recordingController.startRecording(socket, options);
    } catch (error) {
      socket.emit('status', { message: `Recording failed: ${error.message}`, type: 'error' });
    }
  });

  socket.on('stopRecording', () => {
    try {
      recordingController.stopRecording(socket);
    } catch (error) {
      socket.emit('status', { message: `Stop failed: ${error.message}`, type: 'error' });
    }
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
  res.json({
    ok: true,
    providers: transcriptionService.providerStatus(),
  });
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

app.use((error, req, res, next) => {
  if (res.headersSent) {
    next(error);
    return;
  }
  if (error instanceof multer.MulterError) {
    res.status(400).json({ error: error.message || 'Invalid upload' });
    return;
  }
  res.status(error.status || 500).json({ error: error.message || 'Internal server error' });
});

// Start server
const PORT = process.env.PORT || 5000;
async function start() {
  await configService.initialize();
  transcriptionService.initialize();
  server.on('error', (error) => {
    console.error('Server error:', error);
    process.exitCode = 1;
  });
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
