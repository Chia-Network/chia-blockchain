import React, { useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogContentText,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';
import { Trans, t } from '@lingui/macro';
import { AlertDialog, Button, DialogActions, Flex, TooltipIcon, useOpenDialog, Suspender } from '@chia/core';
import { useRemoveKeyringPassphraseMutation, useGetKeyringStatusQuery } from '@chia/api-react';

type Props = {
  onSuccess: () => void;
  onCancel: () => void;
};

export default function RemovePassphrasePrompt(props: Props) {
  const { onSuccess, onCancel } = props;
  const openDialog = useOpenDialog();
  const { data: keyringState, isLoading } = useGetKeyringStatusQuery();
  const [removeKeyringPassphrase, { isLoading: isLoadingRemoveKeyringPassphrase}] = useRemoveKeyringPassphraseMutation();
  let passphraseInput: HTMLInputElement | null;

  const [needsFocusAndSelect, setNeedsFocusAndSelect] = React.useState(false);
  useEffect(() => {
    if (needsFocusAndSelect && passphraseInput) {
      passphraseInput.focus();
      passphraseInput.select();
      setNeedsFocusAndSelect(false);
    }
  });

  if (isLoading) {
    return (
      <Suspender />
    );
  }

  const {
    passphraseHint,
  } = keyringState;

  async function handleSubmit() {
    const passphrase: string | undefined = passphraseInput?.value;

    try {
      if (!passphrase) {
        throw new Error(t`Please enter your passphrase`);
      }

      await removeKeyringPassphrase({
        currentPassphrase: passphrase,
      }).unwrap();

      onSuccess();
    }
    catch (error: any) {
      await openDialog(
        <AlertDialog>
          {error.message}
        </AlertDialog>
      );
      setNeedsFocusAndSelect(true);
    }
  }
  
  function handleCancel() {
    onCancel();
  }

  async function handleKeyDown(e: React.KeyboardEvent) {
    const keyHandlerMapping: { [key: string]: () => Promise<void> } = {
      'Enter' : handleSubmit,
      'Escape' : handleCancel,
    };
    const handler: () => Promise<void> | undefined = keyHandlerMapping[e.key];
  
    if (handler) {
      // Disable default event handling to avoid navigation updates
      e.preventDefault();
      e.stopPropagation();
  
      await handler();
    }
  }

  return (
    <Dialog
      open={true}
      aria-labelledby="form-dialog-title"
      fullWidth={true}
      maxWidth = {'xs'}
      onKeyDown={handleKeyDown}
    >
      <DialogTitle id="form-dialog-title">
        <Trans>Remove Passphrase</Trans>
      </DialogTitle>
      <DialogContent>
        <DialogContentText>
          <Trans>Enter your passphrase:</Trans>
        </DialogContentText>
        <TextField
          autoFocus
          disabled={isLoadingRemoveKeyringPassphrase}
          color="secondary"
          margin="dense"
          id="passphraseInput"
          label={<Trans>Passphrase</Trans>}
          inputRef={(input) => passphraseInput = input}
          type="password"
          fullWidth
        />
        {!!passphraseHint && (
          <Flex gap={1} alignItems="center" style={{ marginTop: '8px' }}>
            <Typography variant="body2" color="textSecondary">
              <Trans>Hint</Trans>
            </Typography>
            <TooltipIcon>
              <Typography variant="inherit">
                {passphraseHint}
              </Typography>
            </TooltipIcon>
          </Flex>
        )}
      </DialogContent>
      <DialogActions>
        <Button
          disabled={isLoadingRemoveKeyringPassphrase}
          onClick={handleCancel}
          color="secondary"
          variant="outlined"
        >
          <Trans>Cancel</Trans>
        </Button>
        <Button
          disabled={isLoadingRemoveKeyringPassphrase}
          onClick={handleSubmit}
          color="primary"
          variant="contained"
        >
          <Trans>Remove Passphrase</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}