import React from 'react';
import { Trans } from '@lingui/macro';
import { makeStyles } from '@material-ui/core/styles';
import {
  AlertDialog,
  Suspender,
  useOpenDialog,
  useSkipMigration,
  SettingsApp,
  SettingsLabel,
  Flex,
  StateTypography,
  State,
} from '@chia/core';
import { useGetKeyringStatusQuery } from '@chia/api-react';
import {
  Grid,
  Typography,
  Box,
  Button,
  Tooltip,
} from '@material-ui/core';
import {
  Help as HelpIcon,
  Lock as LockIcon,
  NoEncryption as NoEncryptionIcon,
} from '@material-ui/icons';
import ChangePassphrasePrompt from './ChangePassphrasePrompt';
import RemovePassphrasePrompt from './RemovePassphrasePrompt';
import SetPassphrasePrompt from './SetPassphrasePrompt';

const useStyles = makeStyles((theme) => ({
  passToggleBox: {
    alignItems: 'center',
  },
  passChangeBox: {
    paddingTop: 20,
  },
  oldPass: {
    paddingRight: 20,
  },
  togglePassButton: {
    marginLeft: theme.spacing(4),
  },
  updatePassButton: {
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),
    height: 56,
    width: 150,
  },
}));


export default function SettingsPanel() {
  const classes = useStyles();
  const openDialog = useOpenDialog();
  const [_skipMigration, setSkipMigration] = useSkipMigration();
  const { data: keyringStatus, isLoading } = useGetKeyringStatusQuery();
  const [changePassphraseOpen, setChangePassphraseOpen] = React.useState(false);
  const [removePassphraseOpen, setRemovePassphraseOpen] = React.useState(false);
  const [addPassphraseOpen, setAddPassphraseOpen] = React.useState(false);

  if (isLoading) {
    return (
      <Suspender />
    );
  }

  const passphraseSupportEnabled = keyringStatus?.passphraseSupportEnabled ?? false; 

  const {
    userPassphraseIsSet,
    needsMigration,
  } = keyringStatus;

  async function changePassphraseSucceeded() {
    closeChangePassphrase();
    await openDialog(
      <AlertDialog>
        <Trans>
          Your passphrase has been updated
        </Trans>
      </AlertDialog>
    );
  }

  async function setPassphraseSucceeded() {
    closeSetPassphrase();
    await openDialog(
      <AlertDialog>
        <Trans>
          Your passphrase has been set
        </Trans>
      </AlertDialog>
    );
  }

  async function removePassphraseSucceeded() {
    closeRemovePassphrase();
    await openDialog(
      <AlertDialog>
        <Trans>
          Passphrase protection has been disabled
        </Trans>
      </AlertDialog>
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
    let icon: JSX.Element | null = null;
    let statusMessage: JSX.Element | null = null;
    let tooltipTitle: React.ReactElement;
    const tooltipIconStyle: React.CSSProperties = { color: '#c8c8c8', fontSize: 12 };

    if (needsMigration) {
      state = State.WARNING;
      icon = (<NoEncryptionIcon style={{ color: 'red',  marginRight: 6 }} />);
      statusMessage = (<Trans>Migration required to support passphrase protection</Trans>);
      tooltipTitle = (<Trans>Passphrase support requires migrating your keys to a new keyring</Trans>);
    } else {
      tooltipTitle = (<Trans>Secure your keychain using a strong passphrase</Trans>);
      
      if (userPassphraseIsSet) {
        state = State.SUCCESS;
        icon = (<LockIcon style={{ color: '#3AAC59',  marginRight: 6 }} />);
        statusMessage = (<Trans>Passphrase protection is enabled</Trans>);
      } else {
        state = State.WARNING;
        icon = (<NoEncryptionIcon style={{ color: 'red',  marginRight: 6 }} />);
        statusMessage = (<Trans>Passphrase protection is disabled</Trans>);
      }
    }

    return (
      <StateTypography variant="body2" state={state}>
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
        <Button
          onClick={() => setSkipMigration(false)}
          variant="outlined"
        >
          <Trans>Migrate Keyring</Trans>
        </Button>
      );
    } else {
      if (userPassphraseIsSet) {
        return (
          <Button
            onClick={() => setRemovePassphraseOpen(true)}
            variant="outlined"
          >
            <Trans>Remove Passphrase</Trans>
          </Button>
        );
      } else {
        return (
          <Button
            onClick={() => setAddPassphraseOpen(true)}
            variant="outlined"
          >
            <Trans>Set Passphrase</Trans>
          </Button>
        );
      }
    }
  }

  return (
    <SettingsApp>
      {passphraseSupportEnabled && (
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
      )}
    </SettingsApp>
  );
}
