import React, { ReactNode, useState } from 'react';
import { Trans } from '@lingui/macro';
import {
  ButtonProps,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
} from '@mui/material';
import DialogActions from '../DialogActions';
import Button from '../Button';
import ButtonLoading from '../ButtonLoading';
import useShowError from '../../hooks/useShowError';

type Props = {
  title?: ReactNode;
  children?: ReactNode;
  open: boolean;
  onClose: (value: boolean) => void;
  confirmTitle: ReactNode;
  cancelTitle: ReactNode;
  confirmColor?: ButtonProps['color'] | 'danger';
  onConfirm?: () => Promise<void>;
};

export default function ConfirmDialog(props: Props) {
  const {
    onClose,
    open,
    title,
    children,
    cancelTitle,
    confirmTitle,
    confirmColor,
    onConfirm,
    ...rest
  } = props;

  const [loading, setLoading] = useState<boolean>(false);
  const showError = useShowError();

  async function handleConfirm() {
    if (onConfirm) {
      try {
        setLoading(true);
        await onConfirm();
      } catch (error: any) {
        showError(error);
      } finally {
        setLoading(false);
      }
    }

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
      {title && <DialogTitle id="alert-dialog-title">{title}</DialogTitle>}
      {children && (
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            {children}
          </DialogContentText>
        </DialogContent>
      )}

      <DialogActions>
        <Button
          onClick={handleCancel}
          color="secondary"
          variant="outlined"
          autoFocus
        >
          {cancelTitle}
        </Button>
        <ButtonLoading
          onClick={handleConfirm}
          color={confirmColor}
          variant="contained"
          loading={loading}
        >
          {confirmTitle}
        </ButtonLoading>
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
