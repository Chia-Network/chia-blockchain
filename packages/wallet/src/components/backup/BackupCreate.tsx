import React from 'react';
import { Trans } from '@lingui/macro';
import { Button, Dialog, DialogContent, DialogContentText, DialogTitle, DialogActions, Modal, Typography } from '@material-ui/core';
import { useSelector, useDispatch } from 'react-redux';
import type { RootState } from '../../modules/rootReducer';
import { showCreateBackup, create_backup_action } from '../../modules/message';
import useSelectFile from '../../hooks/useSelectFile';

export default function BackupCreate() {
  const selectFile = useSelectFile();
  const showBackupModal = useSelector(
    (state: RootState) => state.wallet_state.show_create_backup,
  );
  const dispatch = useDispatch();

  function handleClose() {
    dispatch(showCreateBackup(false));
  }

  async function handleCreateBackup() {
    const filePath = await selectFile();
    if (filePath) {
      dispatch(create_backup_action(filePath));
    }
  }

  return (
    <Modal
      open={showBackupModal}
      onClose={handleClose}
      aria-labelledby="simple-modal-title"
      aria-describedby="simple-modal-description"
    >
      <Dialog
        onClose={handleClose}
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
        open
      >
        <DialogTitle id="alert-dialog-title">
          <Trans>Create a Backup</Trans>
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            <Trans>Backup file is used to restore smart wallets.</Trans>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} variant="outlined">
            <Trans>Cancel</Trans>
          </Button>
          {' '}
          <Button
            color="primary"
            variant="contained"
            onClick={handleCreateBackup}
          >
            <Trans>Create</Trans>
          </Button>
        </DialogActions>
      </Dialog>
    </Modal>
  );
}
