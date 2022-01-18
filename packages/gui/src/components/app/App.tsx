import React from 'react';
import { ModeProvider } from '@chia/core';
import AppRouter from './AppRouter';

console.log('ModeProvider', ModeProvider);

export default function App() {
  return (
    <ModeProvider>
      <AppRouter />
    </ModeProvider>
  );
}
