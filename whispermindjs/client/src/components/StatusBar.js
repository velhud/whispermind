import React from 'react';
import '../styles/StatusBar.css';

const StatusBar = ({ status }) => {
  return (
    <div className={`status-bar ${status.type}`}>
      {status.message}
    </div>
  );
};

export default StatusBar;
