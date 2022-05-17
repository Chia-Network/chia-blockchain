import React from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
} from '@mui/material';
import { Trans } from '@lingui/macro';

type Props = {
  onSuccess: (mnemonicList: string) => void;
  onCancel: () => void;
};

export default function MnemonicPaste(props: Props) {
  const { onSuccess, onCancel } = props;
  let mnemonicListInput: HTMLInputElement | null;

  async function handleSubmit() {
    const mnemonicList: string = mnemonicListInput?.value ?? "";
    onSuccess(mnemonicList);
  }

  async function handleCancel() {
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
      maxWidth = {'md'}
      onKeyDown={handleKeyDown}
    >
      <DialogTitle id="form-dialog-title">
        <Trans>Paste Mnemonic (24 words)</Trans>
      </DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          multiline
          rows={5}
          color="secondary"
          margin="dense"
          id="mnemonicListInput"
          variant="filled"
          inputRef={(input) => mnemonicListInput = input}
          type="password"
          fullWidth
        />
      </DialogContent>
      <DialogActions>
        <Button
          onClick={handleCancel}
          color="secondary"
          variant="contained"
          style={{ marginBottom: '8px', marginRight: '8px' }}
        >
          <Trans>Cancel</Trans>
        </Button>
        <Button
          onClick={handleSubmit}
          color="primary"
          variant="contained"
          style={{ marginBottom: '8px', marginRight: '8px' }}
        >
          <Trans>Import</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}
