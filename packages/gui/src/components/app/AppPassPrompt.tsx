import React, { useEffect, KeyboardEvent } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Typography,
  Button,
} from '@material-ui/core';
import { Trans, t } from '@lingui/macro';
import { PassphrasePromptReason } from '@chia/api';
import { useUnlockKeyringMutation, useGetKeyringStatusQuery } from '@chia/api-react';
import { Flex, TooltipIcon, useShowError, Suspender, ButtonLoading } from '@chia/core';

type Props = {
  reason: PassphrasePromptReason;
};

export default function AppPassPrompt(props: Props) {
  const { reason } = props;
  const showError = useShowError();
  const { data: keyringState, isLoading } = useGetKeyringStatusQuery();
  const [unlockKeyring, { isLoading: isLoadingUnlockKeyring }] = useUnlockKeyringMutation();

  let passphraseInput: HTMLInputElement | null = null;

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
    userPassphraseIsSet,
    passphraseHint,
  } = keyringState;

  async function handleSubmit(): Promise<void> {
    const passphrase: string | undefined = passphraseInput?.value;

    try {
      if (!passphrase) {
        throw new Error(t`Please enter a passphrase`);
      }

      await unlockKeyring({
        key: passphrase,
      }).unwrap();
    } catch (error: any) {
      showError(error);
      setNeedsFocusAndSelect(true);
    }
  }

  function handleKeyDown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      handleSubmit();
    }
  }

  let dialogTitle: React.ReactElement;
  let submitButtonTitle: React.ReactElement;
  let cancellable = true;

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
                disabled={isLoadingUnlockKeyring}
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
            <ButtonLoading
              onClick={handleSubmit}
              color="primary"
              disabled={isLoadingUnlockKeyring}
              loading={isLoadingUnlockKeyring}
              variant="contained"
              style={{ marginBottom: '8px', marginRight: '8px' }}
            >
              {submitButtonTitle}
            </ButtonLoading>
            {cancellable && (
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
