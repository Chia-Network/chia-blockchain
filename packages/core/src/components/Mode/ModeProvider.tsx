import React, { createContext, ReactNode, useState, useMemo, useCallback } from 'react';
import { useLocalStorage, writeStorage } from '@rehooks/local-storage';
import type Mode from '../../constants/Mode';

const LOCAL_STORAGE_KEY = 'mode';

export const ModeContext = createContext<{
  mode?: Mode;
  setMode: (mode: Mode) => void;
} | undefined>(undefined);

export type ModeProviderProps = {
  children: ReactNode;
  mode?: Mode;
  persist?: boolean;
};

export default function ModeProvider(props: ModeProviderProps) {
  const { mode: defaultMode, children, persist = false } = props;
  const [modeState, setModeState] = useState<Mode | undefined>(defaultMode);
  const [modeLocalStorage] = useLocalStorage<Mode | undefined>(LOCAL_STORAGE_KEY, defaultMode);

  const handleSetMode = useCallback((newMode: Mode) => {
    if (persist) {
      writeStorage(LOCAL_STORAGE_KEY, newMode);
    } else {
      setModeState(newMode);
    }
  }, [persist]);

  const mode = persist ? modeLocalStorage : modeState;

  const context = useMemo(() => ({
    mode,
    setMode: handleSetMode,
  }), [mode, handleSetMode]);

  return (
    <ModeContext.Provider value={context}>
      {children}
    </ModeContext.Provider>
  );
}
