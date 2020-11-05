import React, { ReactNode } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
} from '@material-ui/core';
import { Trans } from '@lingui/macro';

type Props = {
  id: number;
  title?: ReactNode;
  body?: ReactNode;
  onClose: (id: number) => void;
};

export default function ModalDialog(props: Props) {
  const { id, body, title, onClose } = props;

  function handleClose() {
    onClose(id);
  }

  return (
    <Dialog
      onClose={handleClose}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      open
    >
      {title && (
        <DialogTitle id="alert-dialog-title">{title}</DialogTitle>
      )}
      {body && (
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            {body}
          </DialogContentText>
        </DialogContent>
      )}
      <DialogActions>
        <Button onClick={handleClose} color="secondary" autoFocus>
          <Trans id="ModalDialog.ok">
            Ok
          </Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}
