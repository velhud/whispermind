import React from 'react';
import '../styles/Header.css';

const Header = ({ backend, isRecording, toggleRecording, showSettings, toggleSettings }) => {
  return (
    <header className="app-header">
      <div className="title-stack">
        <h1 className="app-title">WhisperMind</h1>
        <div className="backend-label">{backend}</div>
      </div>

      <button 
        className={`record-button ${isRecording ? 'recording' : ''}`}
        onClick={toggleRecording}
      >
        {isRecording ? 'Stop Recording' : 'Start Recording'}
      </button>
      
      <label className="settings-toggle">
        <input 
          type="checkbox" 
          checked={showSettings}
          onChange={toggleSettings}
        />
        Settings
      </label>
    </header>
  );
};

export default Header;
