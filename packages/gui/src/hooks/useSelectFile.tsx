import React from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import { AlertDialog } from '@chia/core';
import useOpenDialog from './useOpenDialog';

export default function useSelectFile(): () => Promise<string | undefined> {
  const openDialog = useOpenDialog();

  async function handleSelect(): Promise<string | undefined> {
    if (isElectron()) {
      // @ts-ignore
      const result = await window.remote.dialog.showSaveDialog({});
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
