import React from 'react';
import ModeProvider from '../mode/ModeProvider';
import AppRouter from './AppRouter';

export default function App() {
  return (
    <ModeProvider>
      <AppRouter />
    </ModeProvider>
  );
}
