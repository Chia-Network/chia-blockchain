import React, { useEffect, KeyboardEvent } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Typography,
  Button,
} from '@material-ui/core';
import { Plural, Trans } from '@lingui/macro';
import { AlertDialog, ConfirmDialog, Flex, TooltipIcon } from '@chia/core';
import { openDialog } from '../../modules/dialog';
import { unlock_keyring_action } from '../../modules/message';
import { RootState } from 'modules/rootReducer';
import { KeyringState } from 'modules/keyring';
import PassphrasePromptReason from '../core/constants/PassphrasePromptReason';

type Props = {
  reason: PassphrasePromptReason;
};

export async function validateChangePassphraseParams(
  dispatch: any,
  keyring_state: KeyringState,
  currentPassphrase: string | null,
  newPassphrase: string,
  confirmationPassphrase: string,
): Promise<boolean> {
  let valid: boolean = false;

  if (newPassphrase != confirmationPassphrase) {
    await dispatch(
      openDialog(
        <AlertDialog>
          <Trans>
            The provided passphrase and confirmation do not match
          </Trans>
        </AlertDialog>
      ),
    );
  } else if ((newPassphrase.length == 0 && !keyring_state.allow_empty_passphrase) || // Passphrase required, no passphrase provided
            (newPassphrase.length > 0 && newPassphrase.length < keyring_state.min_passphrase_length)) { // Passphrase provided, not long enough
    await dispatch(
      openDialog(
        <AlertDialog>
          <Plural
            value={keyring_state.min_passphrase_length}
            one="Passphrases must be at least # character in length"
            other="Passphrases must be at least # characters in length"
          />
        </AlertDialog>
      ),
    );
  } else if (currentPassphrase !== null && (currentPassphrase == newPassphrase)) {
    await dispatch(
      openDialog(
        <AlertDialog>
          <Trans>
            New passphrase is the same as your current passphrase
          </Trans>
        </AlertDialog>
      )
    )
  } else if (newPassphrase.length == 0) {
    // Warn about using an empty passphrase
    let alertTitle: React.ReactElement | string;
    let buttonTitle: React.ReactElement | string;
    let message: React.ReactElement | string;

    if (currentPassphrase === null) {
      alertTitle = (<Trans>Skip Passphrase Protection</Trans>);
      buttonTitle = (<Trans>Skip</Trans>);
      message = (<Trans>Setting a passphrase is strongly recommended to protect your keys. Are you sure you want to skip setting a passphrase?</Trans>);
    } else {
      alertTitle = (<Trans>Disable Passphrase Protection</Trans>);
      buttonTitle = (<Trans>Disable</Trans>);
      message = (<Trans>Using a passphrase is strongly recommended to protect your keys. Are you sure you want to disable passphrase protection?</Trans>);
    }

    const useEmptyPassphrase = await dispatch(
      openDialog(
        <ConfirmDialog
          title={alertTitle}
          confirmTitle={buttonTitle}
          confirmColor="danger"
          // @ts-ignore
          maxWidth="xs"
        >
          {message}
        </ConfirmDialog>
      )
    );

    // @ts-ignore
    if (useEmptyPassphrase) {
      valid = true;
    }
  } else {
    valid = true;
  }

  return valid;
}

export default function AppPassPrompt(props: Props): JSX.Element | null {
  const dispatch = useDispatch();
  const { reason } = props;
  const {
    user_passphrase_set: userPassphraseIsSet,
    passphrase_hint: passphraseHint,
  } = useSelector((state: RootState) => state.keyring_state);
  const [actionInProgress, setActionInProgress] = React.useState(false);
  let passphraseInput: HTMLInputElement | null = null;

  const [needsFocusAndSelect, setNeedsFocusAndSelect] = React.useState(false);
  useEffect(() => {
    if (needsFocusAndSelect && passphraseInput) {
      passphraseInput.focus();
      passphraseInput.select();
      setNeedsFocusAndSelect(false);
    }
  });

  async function handleSubmit(): Promise<void> {
    const passphrase: string | undefined = passphraseInput?.value;

    setActionInProgress(true);

    try {
      if (!passphrase || passphrase.length == 0) {
        await dispatch(
          openDialog(
            <AlertDialog>
              <Trans>
                Please enter a passphrase
              </Trans>
            </AlertDialog>
          ),
        );
        setActionInProgress(false);
        setNeedsFocusAndSelect(true);
      } else {
        await dispatch(
          unlock_keyring_action(
            passphrase,
            async () => {
              await dispatch(
                openDialog(
                  <AlertDialog>
                    <Trans>
                      Passphrase is incorrect
                    </Trans>
                  </AlertDialog>
                ),
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
  }

  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      handleSubmit();
    }
  }

  let dialogTitle: React.ReactElement;
  let submitButtonTitle: React.ReactElement;
  let cancellable: boolean = true;

  switch (reason) {
    case PassphrasePromptReason.KEYRING_LOCKED:
      dialogTitle = (
        <div>
          <Typography variant="h6"><Trans>Your keyring is locked</Trans></Typography>
          <Typography variant="subtitle1"><Trans>Please enter your passphrase</Trans></Typography>
        </div>
      );
      submitButtonTitle = (<Trans>Unlock Keyring</Trans>);
      cancellable = false;
      break;
    case PassphrasePromptReason.DELETING_KEY:
      dialogTitle = (
        <div>
          <Typography variant="h6"><Trans>Deleting key</Trans></Typography>
          <Typography variant="subtitle1"><Trans>Please enter your passphrase to proceed</Trans></Typography>
        </div>
      );
      submitButtonTitle = (<Trans>Delete Key</Trans>);
      break;
    default:
      dialogTitle = (<Trans>Please enter your passphrase</Trans>);
      submitButtonTitle = (<Trans>Submit</Trans>);
      break;
  }

  if (userPassphraseIsSet) {
    return (
      <div>
        <Dialog
          onKeyDown={handleKeyDown}
          open={true}
          aria-labelledby="form-dialog-title"
          fullWidth={true}
          maxWidth = {'xs'}
        >
          <DialogTitle id="form-dialog-title">{dialogTitle}</DialogTitle>
          <DialogContent>
            <Flex flexDirection="column" gap={1}>
              <TextField
                autoFocus
                color="secondary"
                disabled={actionInProgress}
                margin="dense"
                id="passphraseInput"
                label={<Trans>Passphrase</Trans>}
                inputRef={(input: HTMLInputElement) => passphraseInput = input}
                type="password"
                fullWidth
              />
              {passphraseHint && passphraseHint.length > 0 && (
                <Flex gap={1} alignItems="center">
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
            </Flex>
          </DialogContent>
          <DialogActions>
            <Button
              onClick={handleSubmit}
              color="primary"
              disabled={actionInProgress}
              variant="contained"
              style={{ marginBottom: '8px', marginRight: '8px' }}
            >
              {submitButtonTitle}
            </Button>
            { cancellable && (
              <Button>
                <Trans>
                  Cancel
                </Trans>
              </Button>
            )}
          </DialogActions>
        </Dialog>
      </div>
    );
  }

  return null;
}
