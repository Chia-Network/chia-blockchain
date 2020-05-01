import React, { Component } from 'react';
import logo from './logo.svg';
import './assets/css/App.css';

class App extends Component {
  render() {
    return (
      <div className="App">
        <div className="App-header">
          <img src={logo} className="App-logo" alt="logo" />
          <h2>Welcome to React/Electron s</h2>
        </div>
        <p className="App-intro">
          Hello Electron!
        </p>
      </div>
    );
  }
}

export default App;
