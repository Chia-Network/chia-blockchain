import React, { ReactNode } from 'react';
import { Button, ButtonProps, Dialog, DialogTitle, DialogContent, DialogActions, DialogContentText } from '@material-ui/core';

type Props = {
  title?: ReactNode,
  children?: ReactNode,
  open: boolean,
  onClose: (value: boolean) => void,
  confirmTitle: ReactNode,
  cancelTitle: ReactNode,
  confirmColor?: ButtonProps['color'],
};

export default function ConfirmDialog(props: Props) {
  const { onClose, open, title, children, cancelTitle, confirmTitle, confirmColor, ...rest } = props;

  function handleConfirm() {
    onClose(true);
  }

  function handleCancel() {
    onClose(false);
  }

  return (
    <Dialog
      onClose={handleCancel}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      open={open}
      {...rest}
    >
      {title && (
        <DialogTitle id="alert-dialog-title">
          {title}
        </DialogTitle>
      )}
      {children && (
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            {children}
          </DialogContentText>
        </DialogContent>
      )}

      <DialogActions>
        <Button onClick={handleCancel} color="secondary" autoFocus>
          {cancelTitle}
        </Button>
        <Button onClick={handleConfirm} color={confirmColor}>
          {confirmTitle}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

ConfirmDialog.defaultProps = {
  open: false,
  onClose: () => {},
  title: undefined,
  children: undefined,
  cancelTitle: 'Cancel',
  confirmTitle: 'Ok',
  confirmColor: 'default',
};
