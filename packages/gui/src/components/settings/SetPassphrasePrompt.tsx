import React, { useEffect } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
  TextField,
  Tooltip,
} from '@material-ui/core';
import {
  Help as HelpIcon,
} from '@material-ui/icons';
import { t, Trans } from '@lingui/macro';
import { AlertDialog, useValidateChangePassphraseParams, useOpenDialog, Suspender } from '@chia/core';
import { useGetKeyringStatusQuery, useSetKeyringPassphraseMutation } from '@chia/api-react';

type Props = {
  onSuccess: () => void;
  onCancel: () => void;
};

export default function SetPassphrasePrompt(props: Props) {
  const { onSuccess, onCancel } = props;
  const openDialog = useOpenDialog();
  const { data: keyringState, isLoading } = useGetKeyringStatusQuery();
  const [setKeyringPassphrase, { isLoading: isLoadingSetKeyringPassphrase }] = useSetKeyringPassphraseMutation();
  const [validateChangePassphraseParams] = useValidateChangePassphraseParams();
  let passphraseInput: HTMLInputElement | null;
  let confirmationInput: HTMLInputElement | null;
  let passphraseHintInput: HTMLInputElement | null;
  let savePassphraseCheckbox: HTMLInputElement | null = null;

  const [needsFocusAndSelect, setNeedsFocusAndSelect] = React.useState(false);
  useEffect(() => {
    if (needsFocusAndSelect && passphraseInput) {
      passphraseInput.focus();
      passphraseInput.select();
      setNeedsFocusAndSelect(false);
    }
  });

  async function validateDialog(passphrase: string, confirmation: string): Promise<boolean> {
    let isValid = false;

    if (passphrase === "" && confirmation === "") {
      await openDialog(
        <AlertDialog>
          <Trans>
            Please enter a passphrase
          </Trans>
        </AlertDialog>
      );
    } else {
      isValid = await validateChangePassphraseParams(null, passphrase, confirmation);
    }

    return isValid;
  }

  async function handleSubmit() {
    const passphrase: string = passphraseInput?.value ?? "";
    const confirmation: string = confirmationInput?.value ?? "";
    const passphraseHint: string = passphraseHintInput?.value ?? "";
    const savePassphrase: boolean = savePassphraseCheckbox?.checked ?? false;
    const isValid = await validateDialog(passphrase, confirmation);

    if (isValid) {
      try {
        await setKeyringPassphrase({
          // currentPassphrase: null,
          newPassphrase: passphrase,
          passphraseHint,
          savePassphrase,
        }).unwrap();

        onSuccess();
      } catch (error: any) {
        await openDialog(
          <AlertDialog>
            <Trans>
              Failed to set passphrase: {error.message}
            </Trans>
          </AlertDialog>
        );
        setNeedsFocusAndSelect(true);
      }
    } else {
      setNeedsFocusAndSelect(true);
    }
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

  if (isLoading) {
    return (
      <Suspender />
    );
  }

  const {
    canSavePassphrase,
    canSetPassphraseHint,
  } = keyringState;

  return (
    <Dialog
      open={true}
      aria-labelledby="form-dialog-title"
      fullWidth={true}
      maxWidth = {'xs'}
      onKeyDown={handleKeyDown}
    >
      <DialogTitle id="form-dialog-title">
        <Trans>Set Passphrase</Trans>
      </DialogTitle>
      <DialogContent>
        <DialogContentText>
          <Trans>
            Enter a strong passphrase to secure your keys:
          </Trans>
        </DialogContentText>
        <TextField
          autoFocus
          disabled={isLoadingSetKeyringPassphrase}
          color="secondary"
          margin="dense"
          id="passphraseInput"
          label={<Trans>Passphrase</Trans>}
          placeholder="Passphrase"
          inputRef={(input) => passphraseInput = input}
          type="password"
          fullWidth
        />
        <TextField
          disabled={isLoadingSetKeyringPassphrase}
          color="secondary"
          margin="dense"
          id="confirmationInput"
          label={<Trans>Confirm Passphrase</Trans>}
          placeholder="Confirm Passphrase"
          inputRef={(input) => confirmationInput = input}
          type="password"
          fullWidth
        />
        {!!canSetPassphraseHint && (
          <TextField
            disabled={isLoadingSetKeyringPassphrase}
            color="secondary"
            margin="dense"
            id="passphraseHintInput"
            label={<Trans>Passphrase Hint (Optional)</Trans>}
            placeholder={t`Passphrase Hint`}
            inputRef={(input) => passphraseHintInput = input}
            fullWidth
          />
        )}
        {!!canSavePassphrase && (
          <Box display="flex" alignItems="center">
            <FormControlLabel
              control={(
                <Checkbox
                  disabled={isLoadingSetKeyringPassphrase}
                  name="cleanupKeyringPostMigration"
                  inputRef={(input) => savePassphraseCheckbox = input}
                />
              )}
              label={t`Save passphrase`}
              style={{ marginRight: '8px' }}
            />
            <Tooltip title={t`Your passphrase can be stored in your system's secure credential store. Chia will be able to access your keys without prompting for your passphrase.`}>
              <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
            </Tooltip>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button
          disabled={isLoadingSetKeyringPassphrase}
          onClick={handleCancel}
          color="secondary"
          variant="contained"
          style={{ marginBottom: '8px', marginRight: '8px' }}
        >
          <Trans>Cancel</Trans>
        </Button>
        <Button
          disabled={isLoadingSetKeyringPassphrase}
          onClick={handleSubmit}
          color="primary"
          variant="contained"
          style={{ marginBottom: '8px', marginRight: '8px' }}
        >
          <Trans>Set Passphrase</Trans>
        </Button>
      </DialogActions>
    </Dialog>
  );
}