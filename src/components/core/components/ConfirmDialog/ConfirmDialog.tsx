import React, { ReactNode } from 'react';
import { Trans } from '@lingui/macro';
import { ButtonProps, Dialog, DialogTitle, DialogContent, DialogContentText } from '@material-ui/core';
import DialogActions from '../DialogActions';
import Button from '../Button';

type Props = {
  title?: ReactNode,
  children?: ReactNode,
  open: boolean,
  onClose: (value: boolean) => void,
  confirmTitle: ReactNode,
  cancelTitle: ReactNode,
  confirmColor?: ButtonProps['color'] | 'danger',
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
        <Button onClick={handleCancel} color="secondary" variant="contained" autoFocus>
          {cancelTitle}
        </Button>
        <Button onClick={handleConfirm} color={confirmColor} variant="contained">
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
  cancelTitle: <Trans>Cancel</Trans>,
  confirmTitle: <Trans>OK</Trans>,
  confirmColor: 'default',
};
