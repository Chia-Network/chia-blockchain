import React from 'react';
import { Dialog, DialogContent, IconButton } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';

type Props = {
  onClose?: () => void;
  children?: React.ReactNode;
  open?: boolean;
};

export default function WalletEmptyDialog(props: Props) {
  const { onClose = () => {}, children, open = false } = props;

  function handleClose() {
    onClose();
  }

  return (
    <Dialog
      onClose={handleClose}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      maxWidth="md"
      open={open}
    >
      <IconButton
        sx={{
          position: 'absolute',
          right: 8,
          top: 8,
          color: (theme) => theme.palette.grey[500],
        }}
        onClick={handleClose}
      >
        <CloseIcon />
      </IconButton>

      <DialogContent>{children}</DialogContent>
    </Dialog>
  );
}
