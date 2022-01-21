import isElectron from 'is-electron';

export default function useShowSaveDialog(): () => Promise<any> {
  async function handleSaveDialog(): Promise<any> {
    if (!isElectron()) {
      throw new Error('useSaveDialog is only available in electron');
    }

    if (!window.ipcRenderer) {
      throw new Error('ipcRenderer is not available');
    }

    return await window.ipcRenderer?.send('showSaveDialog',{});
  }

  return handleSaveDialog;
}
