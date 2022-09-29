import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Button,
  AlertDialog,
  Suspender,
  useOpenDialog,
  useSkipMigration,
  SettingsApp,
  SettingsLabel,
  Flex,
  StateTypography,
  State,
  TooltipIcon,
} from '@chia/core';
import { useGetKeyringStatusQuery } from '@chia/api-react';
import { Tooltip } from '@mui/material';
import { Help as HelpIcon } from '@mui/icons-material';
import ChangePassphrasePrompt from './ChangePassphrasePrompt';
import RemovePassphrasePrompt from './RemovePassphrasePrompt';
import SetPassphrasePrompt from './SetPassphrasePrompt';
import SettingsStartup from './SettingsStartup';
import SettingsDerivationIndex from './SettingsDerivationIndex';

export default function SettingsPanel() {
  const openDialog = useOpenDialog();
  const [, setSkipMigration] = useSkipMigration();
  const { data: keyringStatus, isLoading } = useGetKeyringStatusQuery();
  const [changePassphraseOpen, setChangePassphraseOpen] = React.useState(false);
  const [removePassphraseOpen, setRemovePassphraseOpen] = React.useState(false);
  const [addPassphraseOpen, setAddPassphraseOpen] = React.useState(false);

  if (isLoading) {
    return <Suspender />;
  }

  const { userPassphraseIsSet, needsMigration } = keyringStatus;

  async function changePassphraseSucceeded() {
    closeChangePassphrase();
    await openDialog(
      <AlertDialog>
        <Trans>Your passphrase has been updated</Trans>
      </AlertDialog>,
    );
  }

  async function setPassphraseSucceeded() {
    closeSetPassphrase();
    await openDialog(
      <AlertDialog>
        <Trans>Your passphrase has been set</Trans>
      </AlertDialog>,
    );
  }

  async function removePassphraseSucceeded() {
    closeRemovePassphrase();
    await openDialog(
      <AlertDialog>
        <Trans>Passphrase protection has been disabled</Trans>
      </AlertDialog>,
    );
  }

  function closeChangePassphrase() {
    setChangePassphraseOpen(false);
  }

  function closeSetPassphrase() {
    setAddPassphraseOpen(false);
  }

  function closeRemovePassphrase() {
    setRemovePassphraseOpen(false);
  }

  function PassphraseFeatureStatus() {
    let state: State = null;
    let statusMessage: JSX.Element | null = null;
    let tooltipTitle: React.ReactElement;
    const tooltipIconStyle: React.CSSProperties = {
      color: '#c8c8c8',
      fontSize: 12,
    };

    if (needsMigration) {
      state = State.WARNING;
      statusMessage = (
        <Trans>Migration required to support passphrase protection</Trans>
      );
      tooltipTitle = (
        <Trans>
          Passphrase support requires migrating your keys to a new keyring
        </Trans>
      );
    } else {
      tooltipTitle = (
        <Trans>Secure your keychain using a strong passphrase</Trans>
      );

      if (userPassphraseIsSet) {
        statusMessage = <Trans>Passphrase protection is enabled</Trans>;
      } else {
        state = State.WARNING;
        statusMessage = <Trans>Passphrase protection is disabled</Trans>;
      }
    }

    return (
      <StateTypography variant="body2" state={state} color="textSecondary">
        {statusMessage}
        &nbsp;
        <Tooltip title={tooltipTitle}>
          <HelpIcon style={tooltipIconStyle} />
        </Tooltip>
      </StateTypography>
    );
  }

  function DisplayChangePassphrase() {
    if (needsMigration === false && userPassphraseIsSet) {
      return (
        <>
          <Button
            onClick={() => setChangePassphraseOpen(true)}
            variant="outlined"
            data-testid="changePassphraseAtt"
          >
            <Trans>Change Passphrase</Trans>
          </Button>
          {changePassphraseOpen && (
            <ChangePassphrasePrompt
              onSuccess={changePassphraseSucceeded}
              onCancel={closeChangePassphrase}
            />
          )}
        </>
      );
    }
    return null;
  }

  function ActionButtons() {
    if (needsMigration) {
      return (
        <Button onClick={() => setSkipMigration(false)} variant="outlined">
          <Trans>Migrate Keyring</Trans>
        </Button>
      );
    } else {
      if (userPassphraseIsSet) {
        return (
          <Button
            onClick={() => setRemovePassphraseOpen(true)}
            variant="outlined"
            data-testid="SettingsPanel-remove-passphrase"
          >
            <Trans>Remove Passphrase</Trans>
          </Button>
        );
      } else {
        return (
          <Button
            onClick={() => setAddPassphraseOpen(true)}
            variant="outlined"
            data-testid="SettingsPanel-set-passphrase"
          >
            <Trans>Set Passphrase</Trans>
          </Button>
        );
      }
    }
  }

  return (
    <SettingsApp>
      <Flex flexDirection="column" gap={1}>
        <SettingsLabel>
          <Flex gap={1} alignItems="center">
            <Trans>Derivation Index</Trans>
            <TooltipIcon>
              <Trans>
                The derivation index sets the range of wallet addresses that the
                wallet scans the blockchain for. This number is generally higher
                if you have a lot of transactions or canceled offers for XCH,
                CATs, or NFTs. If you believe your balance is incorrect because
                it’s missing coins, then increasing the derivation index could
                help the wallet include the missing coins in the balance total.
              </Trans>
            </TooltipIcon>
          </Flex>
        </SettingsLabel>

        <SettingsDerivationIndex />
      </Flex>
      <SettingsStartup />
      <Flex flexDirection="column" gap={1}>
        <SettingsLabel>
          <Trans>Passphrase</Trans>
        </SettingsLabel>

        <DisplayChangePassphrase />
        <ActionButtons />
        {removePassphraseOpen && (
          <RemovePassphrasePrompt
            onSuccess={removePassphraseSucceeded}
            onCancel={closeRemovePassphrase}
          />
        )}
        {addPassphraseOpen && (
          <SetPassphrasePrompt
            onSuccess={setPassphraseSucceeded}
            onCancel={closeSetPassphrase}
          />
        )}
        <PassphraseFeatureStatus />
      </Flex>
    </SettingsApp>
  );
}
