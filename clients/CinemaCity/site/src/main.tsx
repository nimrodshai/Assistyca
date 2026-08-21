import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import '@fontsource/rubik/hebrew-400.css';
import '@fontsource/rubik/hebrew-600.css';
import '@fontsource/rubik/hebrew-700.css';
import '@fontsource/secular-one/hebrew-400.css';
import './styles/global.css';
import { App } from './app/App';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
