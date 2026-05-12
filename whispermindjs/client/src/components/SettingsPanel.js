import React, { useEffect, useMemo, useState } from 'react';
import ProfileManager from './ProfileManager';
import '../styles/SettingsPanel.css';

const OPENAI_REALTIME_BACKEND = 'OpenAI Realtime Translation';

const fallbackConstants = {
  backends: [
    'Legacy Groq Whisper + Groq Translate',
    'OpenAI GPT-4o Transcribe + Translate',
    'OpenAI Realtime Translation',
  ],
  transliterationLanguages: ['Russian', 'Spanish', 'French', 'German', 'Chinese', 'Japanese', 'Korean', 'Arabic'],
  textTranslationLanguages: [
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
  ],
  realtimeOutputLanguages: [
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
  ],
};

const SettingsPanel = ({ config, isRecording, onConfigChange }) => {
  const [settings, setSettings] = useState(config);
  const constants = config.constants || fallbackConstants;

  useEffect(() => {
    setSettings(config);
  }, [config]);

  const translationOptions = useMemo(() => (
    settings.translationBackend === OPENAI_REALTIME_BACKEND
      ? constants.realtimeOutputLanguages
      : constants.textTranslationLanguages
  ), [constants, settings.translationBackend]);

  const commit = (patch) => {
    const updated = { ...settings, ...patch };
    if (updated.translationBackend === OPENAI_REALTIME_BACKEND && !constants.realtimeOutputLanguages.includes(updated.translationLanguage)) {
      updated.translationLanguage = 'English';
    }
    setSettings(updated);
    onConfigChange(updated);
  };

  const handlePersonalInfoChange = (field, value) => {
    commit({
      personalInfo: {
        ...(settings.personalInfo || {}),
        [field]: value,
      },
    });
  };

  return (
    <section className="settings-panel">
      <fieldset className="settings-section">
        <legend>Recording</legend>
        <label className="setting-item">
          <span>Chunk seconds</span>
          <input
            type="number"
            min="1"
            max="30"
            value={settings.recordingPeriod}
            disabled={isRecording}
            onChange={(e) => commit({ recordingPeriod: e.target.value })}
            onBlur={(e) => commit({ recordingPeriod: parseInt(e.target.value, 10) || 5 })}
          />
        </label>
        <label className="check-item">
          <input
            type="checkbox"
            checked={settings.timestampMode}
            onChange={(e) => commit({ timestampMode: e.target.checked })}
          />
          Timestamp every minute
        </label>
        <label className="check-item">
          <input
            type="checkbox"
            checked={settings.autoScroll}
            onChange={(e) => commit({ autoScroll: e.target.checked })}
          />
          Auto-scroll
        </label>
        <div className="inline-checks">
          <label className="check-item">
            <input
              type="checkbox"
              checked={settings.showOriginal}
              onChange={(e) => commit({ showOriginal: e.target.checked })}
            />
            Show original
          </label>
          <label className="check-item">
            <input
              type="checkbox"
              checked={settings.showSuggestions}
              onChange={(e) => commit({ showSuggestions: e.target.checked })}
            />
            Show suggestions
          </label>
        </div>
      </fieldset>

      <fieldset className="settings-section backend-section">
        <legend>Backend & Languages</legend>
        <label className="setting-item">
          <span>Mode</span>
          <select
            value={settings.translationBackend}
            disabled={isRecording}
            onChange={(e) => commit({ translationBackend: e.target.value })}
          >
            {constants.backends.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
        <label className="setting-item">
          <span>Translate to</span>
          <select
            value={settings.translationLanguage}
            disabled={isRecording}
            onChange={(e) => commit({ translationLanguage: e.target.value })}
          >
            {translationOptions.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
        <label className="setting-item">
          <span>Transliterate as</span>
          <select
            value={settings.transliterationLanguage}
            onChange={(e) => commit({ transliterationLanguage: e.target.value })}
          >
            {constants.transliterationLanguages.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
      </fieldset>

      <fieldset className="settings-section assistant-section">
        <legend>Suggestions</legend>
        {['name', 'goal', 'style', 'length'].map((field) => (
          <label className="setting-item" key={field}>
            <span>{field[0].toUpperCase() + field.slice(1)}</span>
            <input
              type="text"
              value={settings.personalInfo?.[field] || ''}
              onChange={(e) => handlePersonalInfoChange(field, e.target.value)}
            />
          </label>
        ))}
      </fieldset>

      <ProfileManager config={settings} onConfigChange={onConfigChange} />
    </section>
  );
};

export default SettingsPanel;
