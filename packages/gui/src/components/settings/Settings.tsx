import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { makeStyles } from '@mui/styles';
import {
  AlertDialog,
  Button,
  Card,
  Flex,
  Suspender,
  useOpenDialog,
  useSkipMigration,
  LayoutDashboardSub,
} from '@chia/core';
import { useGetKeyringStatusQuery } from '@chia/api-react';
import {
  Grid,
  Typography,
  Box,
  Tooltip,
  Tab,
  Tabs,
} from '@mui/material';
import {
  Help as HelpIcon,
  Lock as LockIcon,
  NoEncryption as NoEncryptionIcon,
} from '@mui/icons-material';
import ChangePassphrasePrompt from './ChangePassphrasePrompt';
import RemovePassphrasePrompt from './RemovePassphrasePrompt';
import SetPassphrasePrompt from './SetPassphrasePrompt';
import SettingsGeneral from './SettingsGeneral';

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

const SecurityCard = () => {
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

  function PassphraseFeatureStatus(): JSX.Element {
    let icon: JSX.Element | null = null;
    let statusMessage: JSX.Element | null = null;
    let tooltipTitle: React.ReactElement;
    const tooltipIconStyle: React.CSSProperties = { color: '#c8c8c8', fontSize: 12 };

    if (needsMigration) {
      icon = (<NoEncryptionIcon style={{ color: 'red',  marginRight: 6 }} />);
      statusMessage = (<Trans>Migration required to support passphrase protection</Trans>);
      tooltipTitle = (<Trans>Passphrase support requires migrating your keys to a new keyring</Trans>);
    } else {
      tooltipTitle = (<Trans>Secure your keychain using a strong passphrase</Trans>);

      if (userPassphraseIsSet) {
        icon = (<LockIcon style={{ color: '#3AAC59',  marginRight: 6 }} />);
        statusMessage = (<Trans>Passphrase protection is enabled</Trans>);
      } else {
        icon = (<NoEncryptionIcon style={{ color: 'red',  marginRight: 6 }} />);
        statusMessage = (<Trans>Passphrase protection is disabled</Trans>);
      }
    }

    return (
      <Box display="flex" className={classes.passToggleBox}>
        {icon}
        <Typography variant="subtitle1" style={{ marginRight: 5 }}>
          {statusMessage}
        </Typography>
        <Tooltip title={tooltipTitle}>
          <HelpIcon style={tooltipIconStyle} />
        </Tooltip>
      </Box>
    );
  }

  function DisplayChangePassphrase() {
    if (needsMigration === false && userPassphraseIsSet) {
      return (
        <Box display="flex" className={classes.passChangeBox}>
          <Button
            onClick={() => setChangePassphraseOpen(true)}
            className={classes.togglePassButton}
            variant="contained"
            disableElevation
          >
            <Trans>Change Passphrase</Trans>
          </Button>
          { changePassphraseOpen &&
            <ChangePassphrasePrompt
              onSuccess={changePassphraseSucceeded}
              onCancel={closeChangePassphrase}
            />}
        </Box>
      )
    }
    return null;
  }

  function ActionButtons() {
    if (needsMigration) {
      return (
        <Button
          onClick={() => setSkipMigration(false)}
          className={classes.togglePassButton}
          variant="contained"
          disableElevation
        >
          <Trans>Migrate Keyring</Trans>
        </Button>
      )
    } else {
      if (userPassphraseIsSet) {
        return (
          <Button
            onClick={() => setRemovePassphraseOpen(true)}
            className={classes.togglePassButton}
            variant="contained"
            disableElevation
          >
            <Trans>Remove Passphrase</Trans>
          </Button>
        );
      } else {
        return (
          <Button
            onClick={() => setAddPassphraseOpen(true)}
            className={classes.togglePassButton}
            variant="contained"
            disableElevation
          >
            <Trans>Set Passphrase</Trans>
          </Button>
        )
      }
    }
  }

  return (
    <Card title={<Trans>Passphrase Settings</Trans>}>
      <Grid spacing={4} container>
        <Grid item xs={12}>
          <PassphraseFeatureStatus />
          <DisplayChangePassphrase />
          <Box display="flex" className={classes.passChangeBox}>
            <ActionButtons />
            {removePassphraseOpen &&
              <RemovePassphrasePrompt
                onSuccess={removePassphraseSucceeded}
                onCancel={closeRemovePassphrase}
              />}
            {addPassphraseOpen &&
              <SetPassphrasePrompt
                onSuccess={setPassphraseSucceeded}
                onCancel={closeSetPassphrase}
              />}
          </Box>
        </Grid>
      </Grid>
    </Card>
  );
};

export default function Settings() {
  const [activeTab, setActiveTab] = useState<'GENERAL' | 'IDENTITIES'>('GENERAL');

  return (
    <LayoutDashboardSub>
      <Typography variant="h5" gutterBottom>
        <Trans>Settings</Trans>
      </Typography>
      <Flex gap={2} flexDirection="column">
        <Tabs
          value={activeTab}
          onChange={(_event, newValue) => setActiveTab(newValue)}
          textColor="primary"
          indicatorColor="primary"
        >
          <Tab value="GENERAL" label={<Trans>General</Trans>} />
          <Tab value="IDENTITIES" label={<Trans>Identities</Trans>} />
        </Tabs>

        {activeTab === 'GENERAL' && (
          <SettingsGeneral />
        )}
      </Flex>
    </LayoutDashboardSub>
  );
}
