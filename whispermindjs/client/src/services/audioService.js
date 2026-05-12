import axios from 'axios';

const OPENAI_REALTIME_BACKEND = 'OpenAI Realtime Translation';

function floatTo16BitPcm(floatSamples) {
  const pcm = new Int16Array(floatSamples.length);
  for (let i = 0; i < floatSamples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, floatSamples[i]));
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return pcm;
}

function resampleLinear(input, inputRate, outputRate) {
  if (inputRate === outputRate) return input;
  const ratio = inputRate / outputRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i += 1) {
    const sourceIndex = i * ratio;
    const left = Math.floor(sourceIndex);
    const right = Math.min(input.length - 1, left + 1);
    const weight = sourceIndex - left;
    output[i] = input[left] * (1 - weight) + input[right] * weight;
  }

  return output;
}

class AudioService {
  constructor() {
    this.isRecording = false;
    this.socket = null;
    this.stream = null;
    this.audioContext = null;
    this.source = null;
    this.processor = null;
    this.pendingSamples = [];
    this.pendingLength = 0;
    this.targetSampleRate = 16000;
    this.samplesPerPacket = 16000;
  }

  async startRecording(socket, config) {
    if (this.isRecording) return;

    this.socket = socket;
    this.pendingSamples = [];
    this.pendingLength = 0;
    this.targetSampleRate = config.translationBackend === OPENAI_REALTIME_BACKEND ? 24000 : 16000;
    this.samplesPerPacket = this.targetSampleRate;

    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });

    this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    this.source = this.audioContext.createMediaStreamSource(this.stream);
    this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (event) => this.handleAudioProcess(event);
    this.source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);

    this.socket.emit('startRecording', {
      backend: config.translationBackend,
      sampleRate: this.targetSampleRate,
    });
    this.isRecording = true;
  }

  handleAudioProcess(event) {
    if (!this.isRecording || !this.socket) return;

    const input = event.inputBuffer.getChannelData(0);
    const resampled = resampleLinear(input, this.audioContext.sampleRate, this.targetSampleRate);
    this.pendingSamples.push(resampled);
    this.pendingLength += resampled.length;

    while (this.pendingLength >= this.samplesPerPacket) {
      const packet = new Float32Array(this.samplesPerPacket);
      let offset = 0;

      while (offset < packet.length && this.pendingSamples.length > 0) {
        const head = this.pendingSamples[0];
        const take = Math.min(head.length, packet.length - offset);
        packet.set(head.subarray(0, take), offset);
        offset += take;

        if (take === head.length) {
          this.pendingSamples.shift();
        } else {
          this.pendingSamples[0] = head.subarray(take);
        }
      }

      this.pendingLength -= packet.length;
      const pcm = floatTo16BitPcm(packet);
      this.socket.emit('audioData', {
        pcm: pcm.buffer,
        sampleRate: this.targetSampleRate,
      });
    }
  }

  stopRecording() {
    if (!this.isRecording) return;

    this.isRecording = false;
    if (this.processor) {
      this.processor.disconnect();
      this.processor.onaudioprocess = null;
    }
    if (this.source) {
      this.source.disconnect();
    }
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
    }
    if (this.audioContext) {
      this.audioContext.close();
    }

    this.socket = null;
    this.stream = null;
    this.audioContext = null;
    this.source = null;
    this.processor = null;
    this.pendingSamples = [];
    this.pendingLength = 0;
  }

  async transcribeFile(file) {
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await axios.post('/api/transcribe-file', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      return response.data;
    } catch (error) {
      console.error('Error transcribing file:', error);
      throw error.response?.data || error;
    }
  }
}

export const audioService = new AudioService();
