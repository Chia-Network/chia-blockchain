import React, { DragEvent } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import {
  Box,
  Button,
  Paper,
  Grid,
  Typography,
  Container,
} from '@material-ui/core';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useSelector, useDispatch } from 'react-redux';
import { useHistory } from 'react-router';
import { Flex, Link } from '@chia/core';
import {
  add_new_key_action,
  add_and_restore_from_backup,
  login_and_skip_action,
  get_backup_info_action,
  log_in_and_import_backup_action,
} from '../../modules/message';
import {
  changeBackupView,
  presentMain,
  presentBackupInfo,
  setBackupInfo,
  selectFilePath,
} from '../../modules/backup';
import { unix_to_short_date } from '../../util/utils';
import type { RootState } from '../../modules/rootReducer';
import Wallet from '../../types/Wallet';
import myStyle from '../../constants/style';
import LayoutHero from '../layout/LayoutHero';

const StyledDropPaper = styled(Paper)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#424242' : '#F0F0F0'};
  height: 300px;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
`;

function WalletHeader() {
  const classes = myStyle();

  return (
    <Box display="flex" style={{ minWidth: '100%' }}>
      <Box className={classes.column_three} flexGrow={1}>
        <Typography variant="subtitle2"> id</Typography>
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_center}>
          {' '}
          <Typography variant="subtitle2"> name</Typography>
        </div>
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_right}>
          {' '}
          <Typography variant="subtitle2"> type</Typography>
        </div>
      </Box>
    </Box>
  );
}

type WalletRowProps = {
  wallet: Wallet;
};

function WalletRow(props: WalletRowProps) {
  const {
    wallet: {
      id,
      name,
      // @ts-ignore
      type_name: type,
    },
  } = props;
  const classes = myStyle();

  return (
    <Box display="flex" style={{ minWidth: '100%' }}>
      <Box className={classes.column_three} flexGrow={1}>
        {id}
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_center}> {name}</div>
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_right}> {type}</div>
      </Box>
    </Box>
  );
}

function UIPart() {
  const dispatch = useDispatch();
  const classes = myStyle();
  let words = useSelector(
    (state: RootState) => state.mnemonic_state.mnemonic_input,
  );
  const fingerprint = useSelector(
    (state: RootState) => state.wallet_state.selected_fingerprint,
  );

  words.forEach((word) => {
    if (word === '') {
      // @ts-ignore
      words = null;
    }
  });

  function handleSkip() {
    if (fingerprint !== null) {
      dispatch(login_and_skip_action(fingerprint));
    } else if (words !== null) {
      dispatch(add_new_key_action(words));
    }
  }

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();

    const file_path = e.dataTransfer.files[0].path;
    if (fingerprint !== null) {
      dispatch(get_backup_info_action(file_path, fingerprint, null));
    } else if (words !== null) {
      dispatch(get_backup_info_action(file_path, null, words));
    }
  };

  return (
    <LayoutHero
      header={
        <Link to="/">
          <ArrowBackIosIcon fontSize="large" color="secondary" />
        </Link>
      }
    >
      <Container maxWidth="lg">
        <Flex flexDirection="column" gap={3} alignItems="center">
          <Typography variant="h5" component="h1" gutterBottom>
            <Trans>
              Restore Metadata for Coloured Coins and other Smart Wallets from Backup
            </Trans>
          </Typography>

          <StyledDropPaper
            onDrop={(e) => handleDrop(e)}
            onDragOver={(e) => handleDragOver(e)}
            onDragEnter={(e) => handleDragEnter(e)}
            onDragLeave={(e) => handleDragLeave(e)}
          >
            <Typography variant="subtitle1">
              <Trans>
                Drag and drop your backup file
              </Trans>
            </Typography>
          </StyledDropPaper>

          <Container maxWidth="xs">
            <Button
              onClick={handleSkip}
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.submit}
            >
              <Trans>Safe To Skip</Trans>
            </Button>
          </Container>
        </Flex>
      </Container>
    </LayoutHero>
  );
}

function BackupDetails() {
  const history = useHistory();
  const classes = myStyle();
  const dispatch = useDispatch();
  const file_path = useSelector(
    (state: RootState) => state.backup_state.selected_file_path,
  );
  const backupInfo = useSelector(
    (state: RootState) => state.backup_state.backup_info,
  );
  const selected_file_path = useSelector(
    (state: RootState) => state.backup_state.selected_file_path,
  );

  const {
    timestamp,
    version,
    wallets,
    downloaded,
    backup_host: host,
    fingerprint: backup_fingerprint,
  } = backupInfo;

  const date = unix_to_short_date(timestamp);

  let words = useSelector(
    (state: RootState) => state.mnemonic_state.mnemonic_input,
  );
  const fingerprint = useSelector(
    (state: RootState) => state.wallet_state.selected_fingerprint,
  );

  words.forEach((word) => {
    if (word === '') {
      // @ts-ignore
      words = null;
    }
  });

  function handleGoBack() {
    dispatch(changeBackupView(presentMain));
    history.push('/');
  }

  function goBackBackup() {
    dispatch(changeBackupView(presentMain));
    dispatch(setBackupInfo({}));
    // @ts-ignore
    dispatch(selectFilePath(null));
  }

  function next() {
    if (fingerprint !== null) {
      dispatch(log_in_and_import_backup_action(fingerprint, file_path));
    } else if (words !== null) {
      dispatch(add_and_restore_from_backup(words, file_path));
    }
  }

  return (
    <div className={classes.root}>
      <ArrowBackIosIcon onClick={handleGoBack} className={classes.navigator}>
        {' '}
      </ArrowBackIosIcon>
      <div className={classes.grid_wrap}>
        <Container className={classes.grid} maxWidth="lg">
          <Typography className={classes.title} component="h4" variant="h4">
            Restore From Backup
          </Typography>
        </Container>
      </div>
      <div className={classes.dragContainer}>
        <Paper
          className={classes.drag}
          style={{
            position: 'relative',
            width: '80%',
            margin: 'auto',
            padding: '20px',
          }}
        >
          <Box
            display="flex"
            onClick={goBackBackup}
            style={{ cursor: 'pointer', minWidth: '100%' }}
          >
            <Box>
              {' '}
              <ArrowBackIosIcon
                style={{ cursor: 'pointer' }}
                onClick={goBackBackup}
              />
            </Box>
            <Box className={classes.align_left} flexGrow={1}>
              <Typography variant="subtitle2">Import Backup File</Typography>
            </Box>
          </Box>
          <Grid container spacing={3} style={{ marginBottom: 10 }}>
            <Grid item xs={6}>
              <Typography variant="subtitle1">Backup info:</Typography>
              <Box display="flex" style={{ minWidth: '100%' }}>
                <Box flexGrow={1}>Date: </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {date}
                </Box>
              </Box>
              <Box display="flex" style={{ minWidth: '100%' }}>
                <Box flexGrow={1}>Version: </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {version}
                </Box>
              </Box>
              <Box display="flex" style={{ minWidth: '100%' }}>
                <Box flexGrow={1}>Fingerprint: </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {backup_fingerprint}
                </Box>
              </Box>
            </Grid>
            <Grid item xs={6}>
              <Box display="flex" style={{ minWidth: '100%' }}>
                <Box flexGrow={1}>Downloaded: </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {`${downloaded}`}
                </Box>
              </Box>
              <Box display="flex" style={{ minWidth: '100%' }}>
                <Box flexGrow={1}>
                  {downloaded ? 'Backup Host:' : 'File Path'}
                </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {downloaded ? host : selected_file_path}
                </Box>
              </Box>
            </Grid>
          </Grid>
          <Typography variant="subtitle1">Smart wallets</Typography>
          <WalletHeader />
          {!!wallets &&
            wallets.map((wallet: Wallet) => <WalletRow wallet={wallet} />)}
        </Paper>
      </div>
      <Container component="main" maxWidth="xs">
        <div className={classes.paper}>
          <Button
            onClick={next}
            type="submit"
            fullWidth
            variant="contained"
            color="primary"
            className={classes.submit}
          >
            Continue
          </Button>
        </div>
      </Container>
    </div>
  );
}

export default function RestoreBackup() {
  const view = useSelector((state: RootState) => state.backup_state.view);
  if (view === presentBackupInfo) {
    return <BackupDetails />;
  }
  return <UIPart />;
}
