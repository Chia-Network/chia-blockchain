import isElectron from 'is-electron';

export default function useShowSaveDialog(): () => Promise<string[] | undefined> {
  async function handleShowSaveDialog(options: any = {}): Promise<string[] | undefined> {
    if (!isElectron()) {
      throw new Error('useSaveDialog is only available in electron');
    }

    if (!window.ipcRenderer) {
      throw new Error('ipcRenderer is not available');
    }

    console.log('options', options);
    return await window.ipcRenderer?.invoke('showSaveDialog', options);
  }

  return handleShowSaveDialog;
}
