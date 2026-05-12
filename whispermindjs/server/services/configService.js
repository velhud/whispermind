const fs = require('fs').promises;
const path = require('path');
const {
  BACKENDS,
  LEGACY_GROQ_BACKEND,
  OPENAI_REALTIME_BACKEND,
  OPENAI_CHUNKED_BACKEND,
  TRANSLITERATION_LANGUAGES,
  TEXT_TRANSLATION_LANGUAGES,
  REALTIME_OUTPUT_LANGUAGES,
} = require('../constants');

const CONFIG_FILE = path.join(__dirname, '..', 'config.json');

const DEFAULT_CONFIG = {
  recordingPeriod: 5,
  translationBackend: LEGACY_GROQ_BACKEND,
  transliterationLanguage: 'Russian',
  translationLanguage: 'English',
  autoScroll: true,
  timestampMode: false,
  showOriginal: true,
  showSuggestions: true,
  personalInfo: {
    name: '',
    goal: '',
    style: '',
    length: '',
  },
  profiles: {},
};

function cloneConfig(config) {
  return JSON.parse(JSON.stringify(config));
}

function clampRecordingPeriod(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return DEFAULT_CONFIG.recordingPeriod;
  return Math.min(30, Math.max(1, parsed));
}

function mapLegacyKeys(input) {
  const mapped = { ...input };
  const aliases = {
    recording_period: 'recordingPeriod',
    translation_backend: 'translationBackend',
    transliteration_language: 'transliterationLanguage',
    translation_language: 'translationLanguage',
    auto_scroll: 'autoScroll',
    timestamp_mode: 'timestampMode',
    show_original: 'showOriginal',
    show_suggestions: 'showSuggestions',
    personal_info: 'personalInfo',
  };

  for (const [legacyKey, camelKey] of Object.entries(aliases)) {
    if (Object.prototype.hasOwnProperty.call(mapped, legacyKey) && !Object.prototype.hasOwnProperty.call(mapped, camelKey)) {
      mapped[camelKey] = mapped[legacyKey];
    }
    delete mapped[legacyKey];
  }

  return mapped;
}

function sanitizeString(value) {
  return typeof value === 'string' ? value.slice(0, 2000) : '';
}

function sanitizePersonalInfo(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  return {
    name: sanitizeString(source.name),
    goal: sanitizeString(source.goal),
    style: sanitizeString(source.style),
    length: sanitizeString(source.length),
  };
}

function sanitizeConfig(input = {}, base = DEFAULT_CONFIG) {
  const source = mapLegacyKeys(input || {});
  const next = cloneConfig(base);

  if (Object.prototype.hasOwnProperty.call(source, 'recordingPeriod')) {
    next.recordingPeriod = clampRecordingPeriod(source.recordingPeriod);
  }

  if (BACKENDS.includes(source.translationBackend)) {
    next.translationBackend = source.translationBackend;
  }

  if (TRANSLITERATION_LANGUAGES.includes(source.transliterationLanguage)) {
    next.transliterationLanguage = source.transliterationLanguage;
  }

  const languageOptions = next.translationBackend === OPENAI_REALTIME_BACKEND
    ? REALTIME_OUTPUT_LANGUAGES
    : TEXT_TRANSLATION_LANGUAGES;
  if (languageOptions.includes(source.translationLanguage)) {
    next.translationLanguage = source.translationLanguage;
  } else if (!languageOptions.includes(next.translationLanguage)) {
    next.translationLanguage = 'English';
  }

  for (const key of ['autoScroll', 'timestampMode', 'showOriginal', 'showSuggestions']) {
    if (Object.prototype.hasOwnProperty.call(source, key)) {
      next[key] = Boolean(source[key]);
    }
  }

  if (Object.prototype.hasOwnProperty.call(source, 'personalInfo')) {
    next.personalInfo = sanitizePersonalInfo(source.personalInfo);
  }

  if (source.profiles && typeof source.profiles === 'object' && !Array.isArray(source.profiles)) {
    next.profiles = {};
    for (const [name, profile] of Object.entries(source.profiles)) {
      const cleanName = sanitizeString(name).trim();
      if (cleanName) {
        next.profiles[cleanName] = sanitizeConfig(profile, { ...DEFAULT_CONFIG, profiles: {} });
        delete next.profiles[cleanName].profiles;
      }
    }
  }

  return next;
}

const configService = {
  config: cloneConfig(DEFAULT_CONFIG),
  ready: null,

  async initialize() {
    if (this.ready) return this.ready;

    this.ready = (async () => {
      try {
        const fileContent = await fs.readFile(CONFIG_FILE, 'utf8');
        this.config = sanitizeConfig(JSON.parse(fileContent), DEFAULT_CONFIG);
      } catch (error) {
        if (error.code !== 'ENOENT') {
          console.error('Error loading settings:', error);
        }
        this.config = cloneConfig(DEFAULT_CONFIG);
        await this.saveConfig();
      }
      return this.config;
    })();

    return this.ready;
  },

  async ensureReady() {
    await this.initialize();
  },

  getConfig() {
    return cloneConfig(this.config);
  },

  getRuntimeConfig() {
    return this.config;
  },

  getFileBackend() {
    return this.config.translationBackend === OPENAI_REALTIME_BACKEND
      ? OPENAI_CHUNKED_BACKEND
      : this.config.translationBackend;
  },

  async updateConfig(newConfig) {
    await this.ensureReady();
    this.config = sanitizeConfig(newConfig, this.config);
    await this.saveConfig();
    return { success: true, config: this.getConfig() };
  },

  async saveConfig() {
    await fs.writeFile(CONFIG_FILE, JSON.stringify(this.config, null, 2), 'utf8');
    return { success: true };
  },

  async saveProfile(name, profileData = null) {
    await this.ensureReady();
    const cleanName = sanitizeString(name).trim();
    if (!cleanName) {
      return { success: false, error: 'Profile name is required' };
    }

    const source = profileData || this.config;
    const profile = sanitizeConfig(source, DEFAULT_CONFIG);
    delete profile.profiles;
    this.config.profiles[cleanName] = profile;
    await this.saveConfig();
    return { success: true, profileName: cleanName };
  },

  async loadProfile(name) {
    await this.ensureReady();
    const profile = this.config.profiles?.[name];
    if (!profile) {
      return { success: false, error: `Profile "${name}" not found` };
    }

    const profiles = this.config.profiles;
    this.config = sanitizeConfig(profile, { ...this.config, profiles });
    this.config.profiles = profiles;
    await this.saveConfig();
    return { success: true, config: this.getConfig() };
  },

  async getProfiles() {
    await this.ensureReady();
    return Object.keys(this.config.profiles || {});
  },

  constants() {
    return {
      backends: BACKENDS,
      transliterationLanguages: TRANSLITERATION_LANGUAGES,
      textTranslationLanguages: TEXT_TRANSLATION_LANGUAGES,
      realtimeOutputLanguages: REALTIME_OUTPUT_LANGUAGES,
    };
  },
};

module.exports = {
  configService,
  DEFAULT_CONFIG,
  sanitizeConfig,
};
