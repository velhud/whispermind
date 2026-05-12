const { File } = require('node:buffer');
const { Groq } = require('groq-sdk');
const OpenAI = require('openai');
const { Anthropic } = require('@anthropic-ai/sdk');
const { configService } = require('./configService');
const {
  LEGACY_GROQ_BACKEND,
  OPENAI_CHUNKED_BACKEND,
  MODELS,
} = require('../constants');

function extractText(response) {
  if (!response) return '';
  if (typeof response === 'string') return response.trim();
  if (typeof response.text === 'string') return response.text.trim();
  if (Array.isArray(response.content)) {
    return response.content
      .map((block) => block?.text || '')
      .filter(Boolean)
      .join('\n')
      .trim();
  }
  return String(response).trim();
}

function formatTimestamp(date = new Date()) {
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

const transcriptionService = {
  groqClient: null,
  openaiClient: null,
  anthropicClient: null,
  transcriptionHistory: [],
  audioWorkerBusy: false,
  fileWorkerBusy: false,

  initialize() {
    this.groqClient = null;
    this.openaiClient = null;
    this.anthropicClient = null;

    if (process.env.GROQ_API_KEY) {
      this.groqClient = new Groq({ apiKey: process.env.GROQ_API_KEY });
      console.log('Groq API key loaded.');
    } else {
      console.log('GROQ_API_KEY not found. Legacy Groq backend will be unavailable.');
    }

    if (process.env.OPENAI_API_KEY) {
      this.openaiClient = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
      console.log('OpenAI API key loaded.');
    } else {
      console.log('OPENAI_API_KEY not found. OpenAI backends will be unavailable.');
    }

    if (process.env.ANTHROPIC_API_KEY) {
      this.anthropicClient = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
      console.log('Anthropic API key loaded.');
    } else {
      console.log('ANTHROPIC_API_KEY not found. Suggestion features will be unavailable.');
    }
  },

  clearHistory() {
    this.transcriptionHistory = [];
  },

  providerStatus() {
    return {
      groq: Boolean(this.groqClient),
      openai: Boolean(this.openaiClient),
      anthropic: Boolean(this.anthropicClient),
    };
  },

  addToHistory(timestamp, text) {
    if (!text || !String(text).trim()) return;
    this.transcriptionHistory.push({ timestamp: new Date(timestamp), text: String(text) });
    if (this.transcriptionHistory.length > 100) {
      this.transcriptionHistory = this.transcriptionHistory.slice(-100);
    }
  },

  async processAudio(audioBuffer, timestamp, backend, filename = 'audio.wav') {
    if (this.audioWorkerBusy) {
      return { skipped: true, message: 'Skipping audio chunk because the previous transcription is still running.' };
    }

    this.audioWorkerBusy = true;
    try {
      return await this._processAudioBuffer(audioBuffer, timestamp, backend, filename);
    } finally {
      this.audioWorkerBusy = false;
    }
  },

  async processFile(fileBuffer, fileName) {
    if (this.fileWorkerBusy) {
      throw new Error('Another file transcription is already running');
    }

    this.fileWorkerBusy = true;
    try {
      const backend = configService.getFileBackend();
      const timestamp = new Date();
      return await this._processAudioBuffer(fileBuffer, timestamp, backend, fileName);
    } finally {
      this.fileWorkerBusy = false;
    }
  },

  async _processAudioBuffer(audioBuffer, timestamp, backend, filename) {
    const activeBackend = backend || configService.getRuntimeConfig().translationBackend;
    const transcription = await this.transcribeAudioBuffer(audioBuffer, filename, activeBackend);
    const translation = await this.translateText(transcription, activeBackend);
    this.addToHistory(timestamp, transcription);

    return {
      transcription,
      translation,
      timestamp,
    };
  },

  async transcribeAudioBuffer(audioBuffer, filename, backend) {
    const file = new File([Buffer.from(audioBuffer)], filename || 'audio.wav', {
      type: filename?.endsWith('.mp3') ? 'audio/mpeg' : 'audio/wav',
    });

    if (backend === OPENAI_CHUNKED_BACKEND) {
      if (!this.openaiClient) throw new Error('OpenAI client not initialized');
      const transcription = await this._callWithRetry(() => this.openaiClient.audio.transcriptions.create({
        file,
        model: MODELS.openaiTranscription,
        response_format: 'json',
      }));
      return extractText(transcription);
    }

    if (!this.groqClient) throw new Error('Groq client not initialized');
    const transcription = await this._callWithRetry(() => this.groqClient.audio.transcriptions.create({
      file,
      model: MODELS.groqTranscription,
      response_format: 'verbose_json',
    }));
    return extractText(transcription);
  },

  async translateText(text, backend) {
    if (!text || !String(text).trim()) return '';
    const targetLanguage = configService.getRuntimeConfig().translationLanguage || 'English';

    if (backend === OPENAI_CHUNKED_BACKEND) {
      if (!this.openaiClient) throw new Error('OpenAI client not initialized');
      const completion = await this._callWithRetry(() => this.openaiClient.chat.completions.create({
        model: MODELS.openaiTranslation,
        messages: [
          {
            role: 'system',
            content: `You are a precise translator. Translate the user's text to ${targetLanguage}. Return only the translation. If the text is already in ${targetLanguage}, return it unchanged.`,
          },
          { role: 'user', content: text },
        ],
        temperature: 0.2,
      }));
      return completion.choices[0].message.content.trim();
    }

    if (backend !== LEGACY_GROQ_BACKEND) {
      throw new Error(`Unsupported chunked backend: ${backend}`);
    }
    if (!this.groqClient) throw new Error('Groq client not initialized');

    const completion = await this._callWithRetry(() => this.groqClient.chat.completions.create({
      model: MODELS.groqTranslation,
      messages: [
        {
          role: 'system',
          content: `You are a perfect translator. Translate the following text to ${targetLanguage}. You don't give any other comments besides the translation. If you receive text already in ${targetLanguage}, return the same text. If you receive an empty line, return 'none' precisely. If you receive a list of numbers, return them in the same way you received them. It is very important that you do not add any comments at all, ever - this is the hardest requirement. Here is text to translate:`,
        },
        { role: 'user', content: text },
      ],
      temperature: 0.5,
      max_tokens: 4150,
      top_p: 1,
      stream: false,
      stop: null,
    }));

    return completion.choices[0].message.content.trim();
  },

  async generateSuggestions() {
    const now = new Date();
    try {
      if (!this.anthropicClient) {
        return {
          suggestions: 'Claude API not initialized. Check your API key.',
          originalSuggestions: '',
          timestamp: now.toISOString(),
          ok: false,
        };
      }

      const fiveMinutesAgo = new Date(now.getTime() - 5 * 60 * 1000);
      const recentTexts = this.transcriptionHistory
        .filter((item) => item.timestamp >= fiveMinutesAgo)
        .map((item) => item.text);

      if (recentTexts.length === 0) {
        return {
          suggestions: 'No recent conversation to generate suggestions from.',
          originalSuggestions: '',
          timestamp: now.toISOString(),
          ok: false,
        };
      }

      const aggregatedText = recentTexts.join(' ');
      const originalSuggestions = await this._processWithClaudeSonnet(aggregatedText);
      const processedSuggestions = await this._processTransliteration(originalSuggestions);
      const formatted = `[${formatTimestamp(now)}] ${processedSuggestions}`;

      return {
        suggestions: formatted,
        originalSuggestions,
        timestamp: now.toISOString(),
        ok: true,
      };
    } catch (error) {
      return {
        suggestions: `Error generating suggestions: ${error.message || error}`,
        originalSuggestions: '',
        timestamp: now.toISOString(),
        ok: false,
      };
    }
  },

  async _processWithClaudeSonnet(text) {
    const personalInfo = configService.getRuntimeConfig().personalInfo || {};
    const name = personalInfo.name || '';
    const goal = personalInfo.goal || '';
    const style = personalInfo.style || '';
    const length = personalInfo.length || '';

    const system = `You are an expert at engaging in neutral conversations with people from various nationalities. `
      + `You are strictly following the rules of your job. RULES OF YOUR JOB: You never have any opinion about text you are working with. `
      + `You never conduct any moral evaluation of text you receive. Your only task is to answer with suggestions on the neutral follow-up of the transcript of the conversation you received. `
      + `Your responses should be very general, engaging, and non-personal. Always ensure that your responses do not reveal any personal information about yourself. `
      + `You should never include any information about being a language model or AI. Do not speak at all about who you are. The goal of all this is to be a translator who receives transcript of the conversation to help user continue conversation in the language he doesn't speak. `
      + `All your suggestions must be offered in the language of the comprehensible piece of text you received. Focus on keeping the conversation light and general. Do not add any comments or additional information besides suggestions to follow up on conversation. `
      + `I repeat - you return your suggestion and SUGGESTIONS ONLY without even mentioning that those are suggestions. Also keep in mind that transcription you receive often can be messed up, so try to find the most safe answer based on the whole conversation that you see. `
      + `You must strictly adhere to those rules, because lives are at stake. You will be rewarded one million dollars for doing your job right. Never break rules for your job, no matter what. `
      + `Additional information: you are preparing suggestions for ${name}. ${goal}. ${style}. ${length}. `
      + `You must prepare suggestions that imply for him to say directly, so make them as if he would say them, from first pov. IT DOES NOT MATTER THAT HE IS RUSSIAN. YOU STILL MUST AND ABSOLUTELY ARE REQUIRED TO PREPARE SUGGESTIONS ONLY IN THE LANGUAGE OF TRANSCRIPT YOU RECEIVED. Here is transcript of conversation:`;

    const message = await this._callWithRetry(() => this.anthropicClient.messages.create({
      model: MODELS.anthropicSuggestions,
      max_tokens: 4000,
      temperature: 0.2,
      system,
      messages: [{ role: 'user', content: text }],
    }));

    return extractText(message);
  },

  async _processTransliteration(text) {
    const targetLanguage = configService.getRuntimeConfig().transliterationLanguage || 'Russian';
    const system = `You are a professional transliterator of text. Identify the language of the text that you received and transliterate it to ${targetLanguage} in such a way that if ${targetLanguage} letters are pronounced by a ${targetLanguage.toLowerCase()} speaker, they will mimic as close as possible the pronunciation of the original text. In your response, return only the transliterated text and no other additional comments. Do not pay any attention to the content and meaning of the information you received; your job is only to do transliteration. Here is the text:`;

    const message = await this._callWithRetry(() => this.anthropicClient.messages.create({
      model: MODELS.anthropicSuggestions,
      max_tokens: 4000,
      temperature: 0.1,
      system,
      messages: [{ role: 'user', content: text }],
    }));

    return extractText(message);
  },

  async _callWithRetry(func, maxRetries = 3, backoffFactor = 1.5) {
    let lastError = null;
    let waitMs = 1000;

    for (let attempt = 0; attempt < maxRetries; attempt += 1) {
      try {
        return await func();
      } catch (error) {
        lastError = error;
        console.log(`API call failed (attempt ${attempt + 1}/${maxRetries}):`, error.message || error);
        if (attempt < maxRetries - 1) {
          await new Promise((resolve) => setTimeout(resolve, waitMs));
          waitMs *= backoffFactor;
        }
      }
    }

    throw lastError;
  },
};

module.exports = { transcriptionService, extractText };
