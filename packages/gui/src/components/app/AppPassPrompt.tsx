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
import { Trans } from '@lingui/macro';
import { PassphrasePromptReason } from '@chia/api';
import { AlertDialog, Flex, TooltipIcon } from '@chia/core';
import { openDialog } from '../../modules/dialog';
import { unlock_keyring_action } from '../../modules/message';
import { RootState } from 'modules/rootReducer';

type Props = {
  reason: PassphrasePromptReason;
};

export default function AppPassPrompt(props: Props) {
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
