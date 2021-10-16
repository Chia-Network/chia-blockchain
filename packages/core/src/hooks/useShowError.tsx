import React from 'react';
import { Trans } from '@lingui/macro';
import AlertDialog from '../components/AlertDialog';
import useOpenDialog from "./useOpenDialog";

export default function useShowError() {
  const openDialog = useOpenDialog();

  async function showError(error: Error) {
    return openDialog((
      <AlertDialog title={<Trans>Error</Trans>}>
        {error.message}
      </AlertDialog>
    ));
  }
  
  return showError;
}
