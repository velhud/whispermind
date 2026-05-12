import React, { useCallback, useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';
import Header from './components/Header';
import TranscriptionPanel from './components/TranscriptionPanel';
import SettingsPanel from './components/SettingsPanel';
import StatusBar from './components/StatusBar';
import { configService } from './services/configService';
import { audioService } from './services/audioService';
import { suggestionService } from './services/suggestionService';
import './styles/App.css';

const DEFAULT_SUGGESTION = 'Press Space to generate suggestions';

function socketUrl() {
  return process.env.REACT_APP_API_URL || window.location.origin || 'http://localhost:5000';
}

const App = () => {
  const socketRef = useRef(null);
  const [isRecording, setIsRecording] = useState(false);
  const [showSettings, setShowSettings] = useState(true);
  const [config, setConfig] = useState(null);
  const [status, setStatus] = useState({ message: 'Loading application...', type: 'info' });
  const [transcriptionData, setTranscriptionData] = useState({
    original: [],
    translated: [],
    suggestions: DEFAULT_SUGGESTION,
  });

  const appendOriginal = useCallback((text, timestamp = null, streaming = false) => {
    if (!text) return;
    setTranscriptionData((prev) => ({
      ...prev,
      original: streaming && prev.original.length > 0
        ? [
            ...prev.original.slice(0, -1),
            { ...prev.original[prev.original.length - 1], text: `${prev.original[prev.original.length - 1].text}${text}` },
          ]
        : [...prev.original, { text, timestamp }],
    }));
  }, []);

  const appendTranslated = useCallback((text, timestamp = null, streaming = false) => {
    if (!text) return;
    setTranscriptionData((prev) => ({
      ...prev,
      translated: streaming && prev.translated.length > 0
        ? [
            ...prev.translated.slice(0, -1),
            { ...prev.translated[prev.translated.length - 1], text: `${prev.translated[prev.translated.length - 1].text}${text}` },
          ]
        : [...prev.translated, { text, timestamp }],
    }));
  }, []);

  useEffect(() => {
    let mounted = true;

    async function loadInitialData() {
      try {
        const configData = await configService.getConfig();
        if (!mounted) return;
        setConfig(configData);

        const socketInstance = io(socketUrl(), {
          transports: ['websocket', 'polling'],
        });
        socketRef.current = socketInstance;

        socketInstance.on('connect', () => setStatus({ message: 'Ready', type: 'success' }));
        socketInstance.on('disconnect', () => setStatus({ message: 'Disconnected from backend', type: 'warning' }));
        socketInstance.on('status', (statusData) => setStatus(statusData));
        socketInstance.on('transcriptionResult', (result) => {
          appendOriginal(result.original, result.timestamp);
          appendTranslated(result.translated, result.timestamp);
        });
        socketInstance.on('realtimeSourceDelta', ({ delta }) => appendOriginal(delta, null, true));
        socketInstance.on('realtimeTranslationDelta', ({ delta }) => appendTranslated(delta, null, true));
      } catch (error) {
        if (mounted) {
          setStatus({ message: `Error: ${error.message || error.error || error}`, type: 'error' });
        }
      }
    }

    loadInitialData();

    return () => {
      mounted = false;
      audioService.stopRecording();
      socketRef.current?.disconnect();
      socketRef.current = null;
    };
  }, [appendOriginal, appendTranslated]);

  const startRecording = useCallback(async () => {
    try {
      if (!socketRef.current) throw new Error('Socket not connected');
      await audioService.startRecording(socketRef.current, config);
      setIsRecording(true);
      setStatus({ message: 'Recording...', type: 'success' });
    } catch (error) {
      setIsRecording(false);
      setStatus({ message: `Recording failed: ${error.message || error.error || error}`, type: 'error' });
    }
  }, [config]);

  const stopRecording = useCallback(() => {
    try {
      audioService.stopRecording();
      socketRef.current?.emit('stopRecording');
      setIsRecording(false);
      setStatus({ message: 'Recording stopped', type: 'info' });
    } catch (error) {
      setStatus({ message: `Error stopping recording: ${error.message || error.error || error}`, type: 'error' });
    }
  }, []);

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [isRecording, startRecording, stopRecording]);

  const generateSuggestions = useCallback(async () => {
    if (!config?.showSuggestions) {
      setStatus({ message: 'Suggestions are hidden; enable Show Suggestions first', type: 'warning' });
      return;
    }

    try {
      setStatus({ message: 'Generating suggestions...', type: 'info' });
      const result = await suggestionService.generateSuggestions();
      const suggestions = result.suggestions || 'No suggestions returned.';
      setTranscriptionData((prev) => ({ ...prev, suggestions }));
      setStatus({
        message: result.ok ? 'Suggestions generated' : suggestions,
        type: result.ok ? 'success' : 'warning',
      });
    } catch (error) {
      setStatus({ message: `Error generating suggestions: ${error.message || error.error || error}`, type: 'error' });
    }
  }, [config]);

  const handleConfigChange = useCallback(async (newConfig) => {
    try {
      const result = await configService.updateConfig(newConfig);
      setConfig(result.config || newConfig);
      setStatus({ message: 'Settings updated', type: 'success' });
    } catch (error) {
      setStatus({ message: `Error updating config: ${error.message || error.error || error}`, type: 'error' });
    }
  }, []);

  const transcribeFile = useCallback(async (file) => {
    try {
      setStatus({ message: `Transcribing file: ${file.name}...`, type: 'info' });
      const result = await audioService.transcribeFile(file);
      appendOriginal(result.transcription, result.timestamp);
      appendTranslated(result.translation, result.timestamp);
      setStatus({ message: 'File transcribed successfully', type: 'success' });
    } catch (error) {
      setStatus({ message: `Error transcribing file: ${error.message || error.error || error}`, type: 'error' });
    }
  }, [appendOriginal, appendTranslated]);

  const clearText = useCallback(async () => {
    setTranscriptionData({
      original: [],
      translated: [],
      suggestions: DEFAULT_SUGGESTION,
    });
    socketRef.current?.emit('clearHistory');
    await configService.clearHistory().catch(() => null);
    setStatus({ message: 'Cleared transcript and suggestion history', type: 'info' });
  }, []);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.target.closest('input, textarea, select')) return;

      if (event.code === 'Space') {
        event.preventDefault();
        generateSuggestions();
      }

      if (event.code === 'Enter') {
        event.preventDefault();
        toggleRecording();
      }

      if (event.code === 'Escape' && isRecording) {
        event.preventDefault();
        stopRecording();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [generateSuggestions, isRecording, stopRecording, toggleRecording]);

  if (!config) {
    return (
      <div className="app-loading">
        <h2>Loading WhisperMind...</h2>
      </div>
    );
  }

  return (
    <div className="app-container">
      <Header
        backend={config.translationBackend}
        isRecording={isRecording}
        toggleRecording={toggleRecording}
        showSettings={showSettings}
        toggleSettings={() => setShowSettings((value) => !value)}
      />

      <TranscriptionPanel
        transcriptionData={transcriptionData}
        config={config}
        generateSuggestions={generateSuggestions}
        clearText={clearText}
        transcribeFile={transcribeFile}
      />

      {showSettings && (
        <SettingsPanel
          config={config}
          isRecording={isRecording}
          onConfigChange={handleConfigChange}
        />
      )}

      <StatusBar status={status} />
    </div>
  );
};

export default App;
