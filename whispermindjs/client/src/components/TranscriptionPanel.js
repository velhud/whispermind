import React, { useRef, useEffect } from 'react';
import '../styles/TranscriptionPanel.css';

const TranscriptionPanel = ({ 
  transcriptionData,
  config,
  generateSuggestions,
  clearText,
  transcribeFile
}) => {
  const originalRef = useRef(null);
  const translatedRef = useRef(null);
  const suggestionsRef = useRef(null);
  const fileInputRef = useRef(null);
  
  // Auto-scroll effect
  useEffect(() => {
    if (config.autoScroll) {
      if (originalRef.current) {
        originalRef.current.scrollTop = originalRef.current.scrollHeight;
      }
      if (translatedRef.current) {
        translatedRef.current.scrollTop = translatedRef.current.scrollHeight;
      }
    }
  }, [transcriptionData, config.autoScroll]);
  
  const handleFileUpload = () => {
    fileInputRef.current.click();
  };
  
  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      transcribeFile(file);
    }
    // Reset file input
    e.target.value = '';
  };
  
  const formatTranscription = (items) => {
    return items.map((item, index) => {
      const formattedTimestamp = new Date(item.timestamp).toLocaleString();
      return (
        <div key={index} className="transcription-item">
          {config.timestampMode && item.timestamp && (
            <span className="timestamp">[{formattedTimestamp}]</span>
          )}
          <span className="text">{item.text}</span>
        </div>
      );
    });
  };
  
  return (
    <div className="transcription-panel">
      <div className="text-panels">
        {config.showOriginal && (
          <div className="text-panel">
            <h2>Original</h2>
            <div 
              ref={originalRef}
              className="text-content"
            >
              {transcriptionData.original.length > 0 ? (
                formatTranscription(transcriptionData.original)
              ) : (
                <div className="placeholder-text">Listening...</div>
              )}
            </div>
          </div>
        )}
        
        <div className="text-panel">
            <h2>Translation</h2>
          <div 
            ref={translatedRef}
            className="text-content"
          >
            {transcriptionData.translated.length > 0 ? (
              formatTranscription(transcriptionData.translated)
            ) : (
              <div className="placeholder-text">Listening... (translated)</div>
            )}
          </div>
        </div>
        
        {config.showSuggestions && (
          <div className="text-panel">
            <h2>Suggestions</h2>
            <div 
              ref={suggestionsRef}
              className="text-content suggestions"
            >
              {transcriptionData.suggestions}
            </div>
            <button 
              className="generate-suggestions-button"
              onClick={generateSuggestions}
            >
              Generate Suggestions
            </button>
          </div>
        )}
      </div>
      
      <div className="action-buttons">
        <button className="action-button" onClick={handleFileUpload}>
          Transcribe File
        </button>
        <input 
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          accept="audio/*"
          style={{ display: 'none' }}
        />
        
        <button className="action-button" onClick={clearText}>
          Clear Text
        </button>
      </div>
    </div>
  );
};

export default TranscriptionPanel;
