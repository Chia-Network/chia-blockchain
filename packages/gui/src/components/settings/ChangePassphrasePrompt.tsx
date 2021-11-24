import React, { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
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
import { AlertDialog, Flex } from '@chia/core';
import { openDialog } from '../../modules/dialog';
import { change_keyring_passphrase_action, remove_keyring_passphrase_action } from '../../modules/message';
import { validateChangePassphraseParams } from '../app/AppPassPrompt';
import { RootState } from '../../modules/rootReducer';

type Props = {
  onSuccess: () => void;
  onCancel: () => void;
};

export default function ChangePassphrasePrompt(props: Props) {
  const dispatch = useDispatch();
  const { onSuccess, onCancel } = props;
  const keyring_state = useSelector((state: RootState) => state.keyring_state);
  const [actionInProgress, setActionInProgress] = React.useState(false);
  let currentPassphraseInput: HTMLInputElement | null;
  let passphraseInput: HTMLInputElement | null;
  let confirmationInput: HTMLInputElement | null;
  let passphraseHintInput: HTMLInputElement | null;
  let savePassphraseCheckbox: HTMLInputElement | null = null;

  const [needsFocusAndSelect, setNeedsFocusAndSelect] = React.useState(false);
  useEffect(() => {
    if (needsFocusAndSelect && passphraseInput) {
      if (currentPassphraseInput && currentPassphraseInput.value === "") {
        currentPassphraseInput.focus();
        currentPassphraseInput.select();
      } else {
        passphraseInput.focus();
        passphraseInput.select();
      }
      setNeedsFocusAndSelect(false);
    }
  });

  async function validateDialog(currentPassphrase: string, newPassphrase: string, confirmation: string) {
    let isValid: boolean = false;

    if (currentPassphrase === "" && newPassphrase === "" && confirmation === "") {
      await dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please enter your current passphrase, and a new passphrase
            </Trans>
          </AlertDialog>
        )
      );
    } else {
      isValid = await validateChangePassphraseParams(dispatch, keyring_state, currentPassphrase, newPassphrase, confirmation);
    }

    return isValid;
  }

  async function handleSubmit() {
    const currentPassphrase: string = currentPassphraseInput?.value ?? "";
    const newPassphrase: string = passphraseInput?.value ?? "";
    const confirmation: string = confirmationInput?.value ?? "";
    const savePassphrase: boolean = savePassphraseCheckbox?.checked ?? false;
    const passphraseHint: string = passphraseHintInput?.value ?? "";
    const isValid = await validateDialog(currentPassphrase, newPassphrase, confirmation);

    if (isValid) {
      setActionInProgress(true);

      try {
        if (newPassphrase === "") {
          await dispatch(
            remove_keyring_passphrase_action(
              currentPassphrase,
              () => { onSuccess() }, // success
              async (error: string) => { // failure
                await dispatch(
                  openDialog(
                    <AlertDialog>
                      <Trans>
                      Failed to remove passphrase: {error}
                      </Trans>
                    </AlertDialog>
                  )
                );
                setActionInProgress(false);
                setNeedsFocusAndSelect(true);
              }
            )
          )
        } else {
          await dispatch(
            change_keyring_passphrase_action(
              currentPassphrase,
              newPassphrase,
              passphraseHint,
              savePassphrase,
              () => { onSuccess() }, // success
              async (error: string) => { // failure
                await dispatch(
                  openDialog(
                    <AlertDialog>
                      <Trans>
                        Failed to update passphrase: {error}
                      </Trans>
                    </AlertDialog>
                  )
                );
                setActionInProgress(false);
                setNeedsFocusAndSelect(true);
              }
            )
          );
        }
      }
      catch (e) {
        setActionInProgress(false);
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

  return (
    <Dialog
      open={true}
      aria-labelledby="form-dialog-title"
      fullWidth={true}
      maxWidth="sm"
      onKeyDown={handleKeyDown}
    >
      <DialogTitle id="form-dialog-title">Change Passphrase</DialogTitle>
      <DialogContent>
        <DialogContentText>Enter your current passphrase and a new passphrase:</DialogContentText>
        <TextField
          autoFocus
          disabled={actionInProgress}
          color="secondary"
          id="currentPassphraseInput"
          inputRef={(input) => currentPassphraseInput = input}
          label={<Trans>Current Passphrase</Trans>}
          type="password"
          fullWidth
        />
        <TextField
          disabled={actionInProgress}
          color="secondary"
          margin="dense"
          id="passphraseInput"
          inputRef={(input) => passphraseInput = input}
          label={<Trans>New Passphrase</Trans>}
          type="password"
          fullWidth
        />
        <TextField
          disabled={actionInProgress}
          color="secondary"
          margin="dense"
          id="confirmationInput"
          inputRef={(input) => confirmationInput = input}
          label={<Trans>Confirm New Passphrase</Trans>}
          type="password"
          fullWidth
        />
        {keyring_state.can_set_passphrase_hint && (
          <TextField
            disabled={actionInProgress}
            color="secondary"
            margin="dense"
            id="passphraseHintInput"
            label={<Trans>Passphrase Hint (Optional)</Trans>}
            placeholder={t`Passphrase Hint`}
            inputRef={(input) => passphraseHintInput = input}
            fullWidth
          />
        )}
        {keyring_state.can_save_passphrase && (
          <Box display="flex" alignItems="center">
            <FormControlLabel
              control={(
                <Checkbox
                  disabled={actionInProgress}
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
        <DialogActions>
          <Flex gap={2}>
            <Button
              disabled={actionInProgress}
              onClick={handleCancel}
              color="secondary"
              variant="contained"
            >
              <Trans>Cancel</Trans>
            </Button>
            <Button
              disabled={actionInProgress}
              onClick={handleSubmit}
              color="primary"
              variant="contained"
            >
              <Trans>Change Passphrase</Trans>
            </Button>
          </Flex>
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}