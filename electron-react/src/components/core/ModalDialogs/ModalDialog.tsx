import React, { ReactNode } from 'react';
import { Dialog, DialogTitle, DialogContent, DialogContentText, DialogActions, Button } from '@material-ui/core';
import { useDispatch } from 'react-redux';
import { closeDialog } from '../../modules/dialog';

type Props = {
  id: number,
  title: ReactNode,
  text: ReactNode,
  onClose: (id: number) => void,
};

export default function ModalDialog(props: Props) {
  const { id, text, title, onClose } = props;

  function handleClose() {
    onClose(id);
  }

  return (
    <div>
      <Dialog
        onClose={handleClose}
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
        open
      >
        <DialogTitle id="alert-dialog-title">{title}</DialogTitle>
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            {text}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} color="secondary" autoFocus>
            Ok
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
}
