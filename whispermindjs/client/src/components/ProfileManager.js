import React, { useState, useEffect } from 'react';
import { profileService } from '../services/profileService';
import '../styles/ProfileManager.css';

const ProfileManager = ({ config, onConfigChange }) => {
  const [profiles, setProfiles] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState('');
  const [newProfileName, setNewProfileName] = useState('');
  const [status, setStatus] = useState(null);
  
  // Load profiles on component mount
  useEffect(() => {
    loadProfiles();
  }, []);
  
  const loadProfiles = async () => {
    try {
      const profileList = await profileService.getProfiles();
      setProfiles(profileList);
    } catch (error) {
      console.error('Error loading profiles:', error);
      setStatus({ message: `Error loading profiles: ${error.message}`, type: 'error' });
    }
  };
  
  const handleProfileSelect = (e) => {
    setSelectedProfile(e.target.value);
  };
  
  const loadProfile = async () => {
    if (!selectedProfile) {
      setStatus({ message: 'Please select a profile', type: 'error' });
      return;
    }
    
    try {
      setStatus({ message: 'Loading profile...', type: 'info' });
      const result = await profileService.loadProfile(selectedProfile);
      
      if (result.success) {
        onConfigChange(result.config);
        setStatus({ message: `Profile "${selectedProfile}" loaded`, type: 'success' });
      } else {
        setStatus({ message: result.error, type: 'error' });
      }
    } catch (error) {
      console.error('Error loading profile:', error);
      setStatus({ message: `Error: ${error.message}`, type: 'error' });
    }
  };
  
  const saveProfile = async () => {
    if (!newProfileName) {
      setStatus({ message: 'Please enter a profile name', type: 'error' });
      return;
    }
    
    try {
      setStatus({ message: 'Saving profile...', type: 'info' });
      const { constants, ...configToSave } = config;
      const result = await profileService.saveProfile(newProfileName, configToSave);
      
      if (result.success) {
        // Reload profiles
        await loadProfiles();
        setNewProfileName('');
        setStatus({ message: `Profile "${newProfileName}" saved`, type: 'success' });
      } else {
        setStatus({ message: result.error, type: 'error' });
      }
    } catch (error) {
      console.error('Error saving profile:', error);
      setStatus({ message: `Error: ${error.message}`, type: 'error' });
    }
  };
  
  return (
    <div className="profile-manager">
      <h2>Profile Management</h2>
      
      <div className="profile-controls">
        <div className="profile-load">
          <label>Profile:</label>
          <select 
            value={selectedProfile}
            onChange={handleProfileSelect}
          >
            <option value="">Select a profile</option>
            {profiles.map(profile => (
              <option key={profile} value={profile}>{profile}</option>
            ))}
          </select>
          <button onClick={loadProfile}>Load</button>
        </div>
        
        <div className="profile-save">
          <input 
            type="text"
            placeholder="New profile name"
            value={newProfileName}
            onChange={(e) => setNewProfileName(e.target.value)}
          />
          <button onClick={saveProfile}>Save As</button>
        </div>
      </div>
      
      {status && (
        <div className={`profile-status ${status.type}`}>
          {status.message}
        </div>
      )}
    </div>
  );
};

export default ProfileManager;
