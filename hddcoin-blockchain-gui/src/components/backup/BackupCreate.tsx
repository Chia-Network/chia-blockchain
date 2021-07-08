import React from 'react';
import { Trans } from '@lingui/macro';
import { makeStyles } from '@material-ui/core/styles';
import Modal from '@material-ui/core/Modal';
import { Button } from '@material-ui/core';
import { useSelector, useDispatch } from 'react-redux';
import type { RootState } from '../../modules/rootReducer';
import { showCreateBackup, create_backup_action } from '../../modules/message';
import useSelectFile from '../../hooks/useSelectFile';

function getModalStyle() {
  const top = 50;
  const left = 50;

  return {
    top: `${top}%`,
    left: `${left}%`,
    transform: `translate(-${top}%, -${left}%)`,
  };
}

const useStyles = makeStyles((theme) => ({
  paper: {
    position: 'absolute',
    width: 400,
    backgroundColor: theme.palette.background.paper,
    border: '1px solid #000',
    borderRadius: '5px',
    boxShadow: theme.shadows[5],
    padding: theme.spacing(2, 4, 3),
  },
}));

export default function BackupCreate() {
  const selectFile = useSelectFile();
  const showBackupModal = useSelector(
    (state: RootState) => state.wallet_state.show_create_backup,
  );
  const dispatch = useDispatch();
  const classes = useStyles();
  const modalStyle = getModalStyle();

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
      <div style={modalStyle} className={classes.paper}>
        <h2 id="simple-modal-title">
          <Trans>Create a Backup</Trans>
        </h2>
        <p id="simple-modal-description">
          <Trans>Backup file is used to restore smart wallets.</Trans>
        </p>
        <Button
          style={{
            float: 'right',
            width: '100px',
            height: '45px',
            backgroundColor: '#0000dd',
            color: 'white',
          }}
          onClick={handleCreateBackup}
        >
          <Trans>Create</Trans>
        </Button>
      </div>
    </Modal>
  );
}
