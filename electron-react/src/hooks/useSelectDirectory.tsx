import React from 'react';
import isElectron from 'is-electron';
import { Trans } from '@lingui/macro';
import useOpenDialog from './useOpenDialog';

export default function useSelectDirectory(): () => Promise<
  string | undefined
> {
  const openDialog = useOpenDialog();

  async function handleSelect(): Promise<string | undefined> {
    if (isElectron()) {
      // @ts-ignore
      const result = await window.remote.dialog.showOpenDialog({
        properties: ['openDirectory', 'showHiddenFiles'],
      });
      const filePath = result.filePaths[0];

      return filePath;
    } 
      openDialog({
        body: (
          <Trans id="useSelectDirectory.availableOnlyFromElectron">
            This feature is available only from electron app
          </Trans>
        ),
      });
      
    
  }

  return handleSelect;
}
