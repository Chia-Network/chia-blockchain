import React from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import { AlertDialog, useOpenDialog } from '@chia/core';

export default function useSelectFile(): () => Promise<string | undefined> {
  const openDialog = useOpenDialog();

  async function handleSelect(): Promise<string | undefined> {
    if (isElectron()) {
      // @ts-ignore
      const result = await window.ipcRenderer?.send('showSaveDialog',{});
      const { filePath } = result;

      return filePath;
    }

    openDialog(
      <AlertDialog>
        <Trans>This feature is available only from the GUI.</Trans>
      </AlertDialog>,
    );
  }

  return handleSelect;
}
