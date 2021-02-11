import React from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import { AlertDialog } from '@chia/core';
import useOpenDialog from './useOpenDialog';

type Options = {
  buttonLabel?: string;
};

export default function useSelectDirectory(
  defaultOptions?: Options,
): (options?: Options) => Promise<string | undefined> {
  const openDialog = useOpenDialog();

  async function handleSelect(options?: Options): Promise<string | undefined> {
    if (isElectron()) {
      // @ts-ignore
      const result = await window.remote.dialog.showOpenDialog({
        properties: ['openDirectory', 'showHiddenFiles'],
        ...defaultOptions,
        ...options,
      });
      const filePath = result.filePaths[0];

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
