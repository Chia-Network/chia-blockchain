import React from 'react';
import { Trans } from '@lingui/macro';
import LayoutMain from '../layout/LayoutMain';
import { makeStyles } from '@material-ui/core/styles';
import { useDispatch, useSelector } from 'react-redux';
import {
  AlertDialog,
  Flex,
  Card,
} from '@chia/core';
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
import { openDialog } from '../../modules/dialog';
import { RootState } from '../../modules/rootReducer';
import { skipKeyringMigration } from '../../modules/message';
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

const SecurityCard = () => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const { user_passphrase_set: userPassphraseIsSet, needs_migration: needsMigration } = useSelector(
    (state: RootState) => state.keyring_state
  );

  const [changePassphraseOpen, setChangePassphraseOpen] = React.useState(false);
  const [removePassphraseOpen, setRemovePassphraseOpen] = React.useState(false);
  const [addPassphraseOpen, setAddPassphraseOpen] = React.useState(false);

  async function changePassphraseSucceeded() {
    closeChangePassphrase();
    dispatch(
      openDialog(
        <AlertDialog>
          <Trans>
          Your passphrase has been updated
          </Trans>
        </AlertDialog>
      )
    );
  }

  async function setPassphraseSucceeded() {
    closeSetPassphrase();
    dispatch(
      openDialog(
        <AlertDialog>
          <Trans>
            Your passphrase has been set
          </Trans>
        </AlertDialog>
      )
    );
  }

  async function removePassphraseSucceeded() {
    closeRemovePassphrase();
    dispatch(
      openDialog(
        <AlertDialog>
          <Trans>
            Passphrase protection has been disabled
          </Trans>
        </AlertDialog>
      )
    );
  }

  async function closeChangePassphrase() {
    setChangePassphraseOpen(false);
  }

  async function closeSetPassphrase() {
    setAddPassphraseOpen(false);
  }

  async function closeRemovePassphrase() {
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

  function DisplayChangePassphrase(): JSX.Element | null {
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
    else {
      return (null);
    }
  }

  function ActionButtons(): JSX.Element | null {
    if (needsMigration) {
      return (
        <Button
          onClick={() => dispatch(skipKeyringMigration(false))}
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
  return (
    <LayoutMain title={<Trans>Settings</Trans>}>
      <Flex flexDirection="column" gap={3}>
        <SecurityCard />
      </Flex>
    </LayoutMain>
  );
}
