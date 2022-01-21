import { useEffect, useState, useCallback } from 'react';
import isElectron from 'is-electron';

let defaultValue = isElectron() 
  ? window.ipcRenderer?.sendSync('isSimulator')
  : false

export default function useIsSimulator(): boolean {
  const [isSimulator, setIsSimulator] = useState(defaultValue);

  const handleSimulatorModeChange = useCallback((_event, newIsSimulator) => {
    defaultValue = newIsSimulator;
    setIsSimulator(newIsSimulator);
  }, []);

  useEffect(() => {
    if (isElectron()) {
      // @ts-ignore
      window.ipcRenderer.on('simulator-mode', handleSimulatorModeChange);
      return () => {
        // @ts-ignore
        window.ipcRenderer.off('simulator-mode', handleSimulatorModeChange);
      };
    }
  }, []);

  return isSimulator;
}