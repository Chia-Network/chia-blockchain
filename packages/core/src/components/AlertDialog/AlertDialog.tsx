import React, { ReactNode } from 'react';
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@material-ui/core';

type Props = {
  title?: ReactNode;
  children?: ReactNode;
  open: boolean;
  onClose: (value?: any) => void;
};

export default function AlertDialog(props: Props) {
  const { onClose, open, title, children } = props;

  function handleClose() {
    if (onClose) {
      onClose(true);
    }
  }

  function handleHide() {
    if (onClose) {
      onClose();
    }
  }

  return (
    <Dialog
      onClose={handleHide}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      open={open}
    >
      {title && <DialogTitle id="alert-dialog-title">{title}</DialogTitle>}
      {children && (
        <DialogContent id="alert-dialog-description">
            {children}
        </DialogContent>
      )}

      <DialogActions>
        <Button onClick={handleClose} autoFocus>
          Ok
        </Button>
      </DialogActions>
    </Dialog>
  );
}

AlertDialog.defaultProps = {
  open: false,
  title: undefined,
  children: undefined,
  onClose: () => {},
};
