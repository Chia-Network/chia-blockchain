import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Typography,
  Button,
  Box,
  Backdrop,
  CircularProgress,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';

import { useDispatch, useSelector } from 'react-redux';
import ArrowBackIosIcon from '@material-ui/icons/ArrowBackIos';
import {
  createState,
  changeCreateWallet,
  CREATE_RL_WALLET_OPTIONS,
} from '../../../modules/createWallet';
import { useStyles } from './WalletCreate';
import { create_rl_user_action } from '../../../modules/message';

export const customStyles = makeStyles((theme) => ({
  walletContainer: {
    marginBottom: theme.spacing(5),
  },
  topTitleCard: {
    paddingTop: theme.spacing(6),
    paddingBottom: theme.spacing(1),
  },
  input: {
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    paddingRight: theme.spacing(3),
    height: 56,
  },
  inputTitleLeft: {
    marginLeft: theme.spacing(3),
    paddingBottom: theme.spacing(3),
    width: 400,
  },
  createButton: {
    marginBottom: theme.spacing(2),
    width: 150,
    height: 50,
  },
  card: {
    height: 100,
  },
}));

export const CreateRLUserWallet = () => {
  const classes = useStyles();
  const custom = customStyles();
  const dispatch = useDispatch();
  const pending = useSelector((state) => state.create_options.pending);
  const created = useSelector((state) => state.create_options.created);

  function goBack() {
    dispatch(changeCreateWallet(CREATE_RL_WALLET_OPTIONS));
  }

  function create() {
    dispatch(createState(true, true));
    dispatch(create_rl_user_action());
  }

  return (
    <div>
      <div className={classes.cardTitle}>
        <Box display="flex">
          <Box>
            <Button onClick={goBack}>
              <ArrowBackIosIcon />
            </Button>
          </Box>
          <Box flexGrow={1} className={classes.title}>
            <Typography component="h6" variant="h6">
              <Trans>
                Create Rate Limited User Wallet
              </Trans>
            </Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.topTitleCard}>
        <Box display="flex">
          <Box flexGrow={1} className={custom.inputTitleLeft}>
            <Typography variant="subtitle1">
              <Trans>
                Initialize a Rate Limited User Wallet:
              </Trans>
            </Typography>
          </Box>
        </Box>
        <Box display="flex">
          <Box flexGrow={1} className={custom.inputTitleLeft}>
            <Button
              onClick={create}
              className={custom.createButton}
              variant="contained"
              color="primary"
            >
              <Trans>Create</Trans>
            </Button>
          </Box>
        </Box>
      </div>
      <Backdrop className={classes.backdrop} open={pending && created}>
        <CircularProgress color="inherit" />
      </Backdrop>
    </div>
  );
};
