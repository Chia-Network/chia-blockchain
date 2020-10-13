import React from 'react';
import { makeStyles } from '@material-ui/core/styles';
import Modal from '@material-ui/core/Modal';
import { Button } from '@material-ui/core';
import isElectron from 'is-electron';
import { useSelector, useDispatch } from 'react-redux';
import type { RootState } from '../../modules/rootReducer';
import { showCreateBackup, create_backup_action } from '../../modules/message';
import { openDialog } from '../../modules/dialog';

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
  const showBackupModal = useSelector(
    (state: RootState) => state.wallet_state.show_create_backup,
  );
  const dispatch = useDispatch();
  const classes = useStyles();
  const modalStyle = getModalStyle();

  function handleClose() {
    console.log('Modal dialog closed');
    dispatch(showCreateBackup(false));
  }

  async function handleCreateBackup() {
    if (isElectron()) {
      // @ts-ignore
      const result = await window.remote.dialog.showSaveDialog({});
      const { filePath } = result;
      dispatch(create_backup_action(filePath));
    } else {
      dispatch(
        openDialog('', 'This feature is available only from electron app'),
      );
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
        <h2 id="simple-modal-title">Create a Backup</h2>
        <p id="simple-modal-description">
          Backup file is used to restore smart wallets.
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
          Create
        </Button>
      </div>
    </Modal>
  );
}
