const LEGACY_GROQ_BACKEND = 'Legacy Groq Whisper + Groq Translate';
const OPENAI_CHUNKED_BACKEND = 'OpenAI GPT-4o Transcribe + Translate';
const OPENAI_REALTIME_BACKEND = 'OpenAI Realtime Translation';

const BACKENDS = [
  LEGACY_GROQ_BACKEND,
  OPENAI_CHUNKED_BACKEND,
  OPENAI_REALTIME_BACKEND,
];

const LANGUAGE_CODES = {
  English: 'en',
  Spanish: 'es',
  French: 'fr',
  German: 'de',
  Chinese: 'zh',
  Japanese: 'ja',
  Korean: 'ko',
  Arabic: 'ar',
  Russian: 'ru',
  Italian: 'it',
  Portuguese: 'pt',
  Hindi: 'hi',
  Indonesian: 'id',
  Vietnamese: 'vi',
};

const TRANSLITERATION_LANGUAGES = [
  'Russian',
  'Spanish',
  'French',
  'German',
  'Chinese',
  'Japanese',
  'Korean',
  'Arabic',
];

const TEXT_TRANSLATION_LANGUAGES = [
  'English',
  'Spanish',
  'French',
  'German',
  'Chinese',
  'Japanese',
  'Korean',
  'Arabic',
  'Russian',
  'Italian',
  'Portuguese',
  'Hindi',
  'Indonesian',
  'Vietnamese',
];

const REALTIME_OUTPUT_LANGUAGES = [
  'Spanish',
  'Portuguese',
  'French',
  'Japanese',
  'Russian',
  'Chinese',
  'German',
  'Korean',
  'Hindi',
  'Indonesian',
  'Vietnamese',
  'Italian',
  'English',
];

const MODELS = {
  groqTranscription: 'whisper-large-v3',
  groqTranslation: 'llama-3.3-70b-versatile',
  openaiTranscription: 'gpt-4o-transcribe',
  openaiTranslation: 'gpt-4.1-mini',
  openaiRealtimeTranslation: 'gpt-realtime-translate',
  openaiRealtimeTranscription: 'gpt-realtime-whisper',
  anthropicSuggestions: 'claude-sonnet-4-6',
};

function languageCode(languageName) {
  return LANGUAGE_CODES[languageName] || String(languageName || '').slice(0, 2).toLowerCase();
}

module.exports = {
  LEGACY_GROQ_BACKEND,
  OPENAI_CHUNKED_BACKEND,
  OPENAI_REALTIME_BACKEND,
  BACKENDS,
  LANGUAGE_CODES,
  TRANSLITERATION_LANGUAGES,
  TEXT_TRANSLATION_LANGUAGES,
  REALTIME_OUTPUT_LANGUAGES,
  MODELS,
  languageCode,
};
