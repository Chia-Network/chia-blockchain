import isElectron from 'is-electron';

export default function useOpenExternal(): (url: string) => void {
  function handleOpen(url: string) {
    if (isElectron()) {
      // @ts-ignore
      window.shell.openExternal(url);
      return;
    }

    window.open(url, '_blank');
  }

  return handleOpen;
}
