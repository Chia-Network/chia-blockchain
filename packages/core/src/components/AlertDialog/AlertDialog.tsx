import React, { ReactNode } from 'react';
import { Dialog, DialogTitle, DialogContent } from '@mui/material';
import { Trans } from '@lingui/macro';
import DialogActions from '../DialogActions';
import Button from '../Button';
import type { ButtonProps } from '../Button';

export type AlertDialogProps = {
  title?: ReactNode;
  children?: ReactNode;
  open?: boolean;
  onClose?: (value?: any) => void;
  confirmTitle?: ReactNode;
  confirmVariant?: ButtonProps['variant'];
};

export default function AlertDialog(props: AlertDialogProps) {
  const {
    onClose = () => {},
    open = false,
    title,
    confirmTitle = <Trans>OK</Trans>,
    confirmVariant = 'outlined',
    children,
  } = props;

  function handleClose() {
    onClose?.(true);
  }

  function handleHide() {
    onClose?.();
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
        <DialogContent id="alert-dialog-description">{children}</DialogContent>
      )}

      <DialogActions>
        <Button
          onClick={handleClose}
          variant={confirmVariant}
          color="primary"
          autoFocus
        >
          {confirmTitle}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
