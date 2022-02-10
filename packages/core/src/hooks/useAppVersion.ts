import { useState, useEffect } from 'react';

export default function useAppVersion() {
  const [version, setVersion] = useState<string | undefined>(undefined);

  async function getVersion() {
    const currentVersion = await window.ipcRenderer.invoke('getVersion');
    setVersion(currentVersion);
  }

  useEffect(() => {
    getVersion();
  }, []);

  return {
    version,
    isLoading: version === undefined,
  };
}
