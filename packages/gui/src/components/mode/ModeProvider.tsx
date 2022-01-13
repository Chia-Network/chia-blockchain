import React, { createContext, ReactNode, useState, useMemo } from 'react';
import type Mode from '../../constants/Mode';

export const ModeContext = createContext<{
  mode?: Mode;
  setMode: (mode: Mode) => void;
} | undefined>(undefined);

export type ModeProviderProps = {
  children: ReactNode;
  mode?: Mode;
};

export default function ModeProvider(props: ModeProviderProps) {
  const { mode: defaultMode, children } = props;
  const [mode, setMode] = useState<Mode | undefined>(defaultMode);

  const context = useMemo(() => ({
    mode,
    setMode,
  }), [mode, setMode]);

  return (
    <ModeContext.Provider value={context}>
      {children}
    </ModeContext.Provider>
  );
}