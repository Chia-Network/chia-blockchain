import { useContext } from 'react';
import { ModeContext } from '../components/Mode/ModeProvider';
import type Mode from '../constants/Mode';

export default function useMode(): [Mode, (newMode: Mode) => void] {
  const context = useContext(ModeContext);
  console.log('context', context, ModeContext);
  if (!context) {
    throw new Error('useMode must be used within a ModeProvider');
  }

  const { mode, setMode } = context;
  return [mode, setMode];
}
