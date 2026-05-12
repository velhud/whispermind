const WebSocket = require('ws');
const { audioService } = require('../services/audioService');
const { transcriptionService } = require('../services/transcriptionService');
const { configService } = require('../services/configService');
const {
  OPENAI_REALTIME_BACKEND,
  MODELS,
  languageCode,
} = require('../constants');

function normalizePcmChunk(payload) {
  if (!payload) return null;
  const source = payload.pcm || payload.audio || payload;
  if (Buffer.isBuffer(source)) return source;
  if (source instanceof ArrayBuffer) return Buffer.from(source);
  if (ArrayBuffer.isView(source)) return Buffer.from(source.buffer, source.byteOffset, source.byteLength);
  if (Array.isArray(source)) return Buffer.from(source);
  return null;
}

function emitStatus(socket, message, type = 'info') {
  socket.emit('status', { message, type });
}

class RealtimeSocketSession {
  constructor(socket, targetLanguage) {
    this.socket = socket;
    this.targetLanguage = targetLanguage;
    this.ws = null;
    this.running = false;
    this.sourceBuffer = '';
  }

  start() {
    if (!process.env.OPENAI_API_KEY) {
      throw new Error('OPENAI_API_KEY is required for OpenAI realtime translation');
    }

    this.ws = new WebSocket(`wss://api.openai.com/v1/realtime/translations?model=${MODELS.openaiRealtimeTranslation}`, {
      headers: {
        Authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
        'OpenAI-Safety-Identifier': 'whispermind-js-local-user',
      },
    });

    this.ws.on('open', () => {
      this.running = true;
      this.ws.send(JSON.stringify({
        type: 'session.update',
        session: {
          audio: {
            input: {
              transcription: {
                model: MODELS.openaiRealtimeTranscription,
              },
            },
            output: {
              language: languageCode(this.targetLanguage),
            },
          },
        },
      }));
      emitStatus(this.socket, 'OpenAI realtime translation started', 'success');
    });

    this.ws.on('message', (raw) => this.handleEvent(raw));
    this.ws.on('error', (error) => emitStatus(this.socket, `Realtime API error: ${error.message}`, 'error'));
    this.ws.on('close', () => {
      this.running = false;
      this.flushSourceBuffer();
      emitStatus(this.socket, 'Realtime session stopped', 'info');
    });
  }

  appendAudio(pcmBuffer) {
    if (!this.running || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({
      type: 'session.input_audio_buffer.append',
      audio: pcmBuffer.toString('base64'),
    }));
  }

  stop() {
    this.flushSourceBuffer();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
    this.running = false;
  }

  handleEvent(raw) {
    let event;
    try {
      event = JSON.parse(raw.toString());
    } catch (error) {
      emitStatus(this.socket, `Realtime parse error: ${error.message}`, 'error');
      return;
    }

    if (event.type === 'session.output_transcript.delta') {
      const delta = event.delta || '';
      this.socket.emit('realtimeTranslationDelta', { delta });
      return;
    }

    if (event.type === 'session.input_transcript.delta') {
      const delta = event.delta || '';
      this.sourceBuffer += delta;
      this.socket.emit('realtimeSourceDelta', { delta });
      return;
    }

    if (event.type === 'error') {
      const message = event.error?.message || JSON.stringify(event.error || event);
      emitStatus(this.socket, `Realtime API error: ${message}`, 'error');
      this.stop();
    }
  }

  flushSourceBuffer() {
    const text = this.sourceBuffer.trim();
    this.sourceBuffer = '';
    if (text) {
      transcriptionService.addToHistory(new Date(), text);
    }
  }
}

const recordingController = {
  sessions: new Map(),

  startRecording(socket, options = {}) {
    const config = configService.getRuntimeConfig();
    const backend = options.backend || config.translationBackend;
    const sampleRate = Number(options.sampleRate) || (backend === OPENAI_REALTIME_BACKEND ? 24000 : 16000);
    this.stopRecording(socket, { silent: true });

    const state = {
      isRecording: true,
      backend,
      sampleRate,
      audioBuffer: [],
      overlapBuffer: [],
      bufferedBytes: 0,
      processing: false,
      realtimeSession: null,
    };

    if (backend === OPENAI_REALTIME_BACKEND) {
      state.realtimeSession = new RealtimeSocketSession(socket, config.translationLanguage);
      state.realtimeSession.start();
    }

    this.sessions.set(socket.id, state);
    emitStatus(socket, backend === OPENAI_REALTIME_BACKEND ? 'Recording with OpenAI realtime translation' : 'Recording started', 'success');
  },

  stopRecording(socket, options = {}) {
    const state = this.sessions.get(socket.id);
    if (!state) return;

    state.isRecording = false;
    if (state.realtimeSession) {
      state.realtimeSession.stop();
    } else if (state.audioBuffer.length > 0) {
      this._processAudioBuffer(socket, state);
    }

    this.sessions.delete(socket.id);
    if (!options.silent) {
      emitStatus(socket, 'Recording stopped', 'info');
    }
  },

  clearSession(socket) {
    this.stopRecording(socket, { silent: true });
  },

  processAudioChunk(payload, socket) {
    const state = this.sessions.get(socket.id);
    if (!state?.isRecording) return;

    const pcmBuffer = normalizePcmChunk(payload);
    if (!pcmBuffer || pcmBuffer.length === 0) return;

    if (state.backend === OPENAI_REALTIME_BACKEND) {
      state.realtimeSession?.appendAudio(pcmBuffer);
      return;
    }

    state.audioBuffer.push(pcmBuffer);
    state.bufferedBytes += pcmBuffer.length;

    const recordPeriod = configService.getRuntimeConfig().recordingPeriod || 5;
    const requiredBytes = recordPeriod * state.sampleRate * 2;
    if (state.bufferedBytes >= requiredBytes) {
      this._processAudioBuffer(socket, state);
    }
  },

  async _processAudioBuffer(socket, state) {
    if (state.processing || state.audioBuffer.length === 0) return;
    state.processing = true;

    const processingBuffer = [...state.overlapBuffer, ...state.audioBuffer];
    const overlapBytes = Math.floor(0.5 * state.sampleRate * 2);
    const combined = Buffer.concat(state.audioBuffer);
    state.overlapBuffer = combined.length > overlapBytes ? [combined.slice(combined.length - overlapBytes)] : [combined];
    state.audioBuffer = [];
    state.bufferedBytes = 0;

    try {
      const wavBuffer = audioService.convertPcmChunksToWav(processingBuffer, state.sampleRate);
      const timestamp = new Date();
      const result = await transcriptionService.processAudio(wavBuffer, timestamp, state.backend);
      if (result.skipped) {
        emitStatus(socket, result.message, 'warning');
      } else {
        socket.emit('transcriptionResult', {
          original: result.transcription,
          translated: result.translation,
          timestamp: result.timestamp,
        });
      }
    } catch (error) {
      emitStatus(socket, `Error processing audio: ${error.message}`, 'error');
    } finally {
      state.processing = false;
    }
  },
};

module.exports = { recordingController };
