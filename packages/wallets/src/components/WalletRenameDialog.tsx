import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { Button, Dialog, DialogTitle, DialogContent } from '@mui/material';
import {
  AlertDialog,
  ButtonLoading,
  DialogActions,
  Flex,
  Form,
  TextField,
  useOpenDialog,
} from '@chia/core';

type WalletRenameDialogFormData = {
  name: string;
};

type Props = {
  name: string;
  onSave: (name: string) => Promise<void>;
  open?: boolean;
  onClose?: (value: boolean) => void;
};

export default function WalletRenameDialog(props: Props) {
  const { onClose = () => {}, open = false, name, onSave } = props;

  const openDialog = useOpenDialog();
  const methods = useForm<WalletRenameDialogFormData>({
    defaultValues: {
      name,
    },
  });

  const {
    formState: { isSubmitting },
  } = methods;

  function handleCancel() {
    onClose(false);
  }

  async function handleSubmit(values: WalletRenameDialogFormData) {
    const { name: newName } = values;
    if (!newName) {
      openDialog(
        <AlertDialog>
          <Trans>Please enter valid wallet name</Trans>
        </AlertDialog>
      );
      return;
    }

    await onSave(newName);

    onClose(true);
  }

  return (
    <Dialog
      onClose={handleCancel}
      aria-labelledby="alert-dialog-title"
      aria-describedby="alert-dialog-description"
      maxWidth="md"
      open={open}
    >
      <DialogTitle id="alert-dialog-title">
        <Trans>Rename Wallet</Trans>
      </DialogTitle>

      <Form methods={methods} onSubmit={handleSubmit}>
        <DialogContent dividers>
          <Flex flexDirection="column" gap={2}>
            <TextField
              name="name"
              variant="outlined"
              label={<Trans>Nickname</Trans>}
              fullWidth
            />
          </Flex>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={handleCancel}
            color="secondary"
            variant="outlined"
            autoFocus
          >
            <Trans>Cancel</Trans>
          </Button>
          <ButtonLoading
            type="submit"
            color="primary"
            variant="contained"
            loading={isSubmitting}
          >
            <Trans>Save</Trans>
          </ButtonLoading>
        </DialogActions>
      </Form>
    </Dialog>
  );
}
