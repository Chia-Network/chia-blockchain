import React from 'react';
import { Trans } from '@lingui/macro';
import { AlertDialog } from '@chia/core';
import {
  Typography,
  Button,
  Box,
  TextField,
  Backdrop,
  CircularProgress,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';

import { useDispatch, useSelector } from 'react-redux';
import ArrowBackIosIcon from '@material-ui/icons/ArrowBackIos';
import {
  createState,
  changeCreateWallet,
  CREATE_CC_WALLET_OPTIONS,
} from '../../../modules/createWallet';
import { useStyles } from './WalletCreate';
import { chia_to_mojo } from '../../../util/chia';
import { create_cc_for_colour_action } from '../../../modules/message';
import { openDialog } from '../../../modules/dialog';

export const customStyles = makeStyles((theme) => ({
  input: {
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    paddingRight: theme.spacing(3),
    height: 56,
  },
  send: {
    paddingLeft: '0px',
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),

    height: 56,
    width: 150,
  },
  card: {
    paddingTop: theme.spacing(10),
    height: 200,
  },
  backdrop: {
    zIndex: theme.zIndex.drawer + 1,
    color: '#fff',
  },
}));

export const CreateExistingCCWallet = () => {
  const classes = useStyles();
  const custom = customStyles();
  const dispatch = useDispatch();
  let colour_string = null;
  let fee_input = null;
  const open = false;
  const pending = useSelector((state) => state.create_options.pending);
  const created = useSelector((state) => state.create_options.created);

  function goBack() {
    dispatch(changeCreateWallet(CREATE_CC_WALLET_OPTIONS));
  }

  function create() {
    if (fee_input.value === '' || isNaN(Number(fee_input.value))) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please enter a valid numeric fee
            </Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    dispatch(createState(true, true));
    const colour = colour_string.value;
    const fee = chia_to_mojo(fee_input.value);
    dispatch(create_cc_for_colour_action(colour, fee));
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
                Create wallet for colour
              </Trans>
            </Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.card}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              className={custom.input}
              id="filled-secondary" // lgtm [js/duplicate-html-id]
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={(input) => {
                colour_string = input;
              }}
              label={
                <Trans>
                  Colour String
                </Trans>
              }
            />
          </Box>
          <Box flexGrow={1}>
            <TextField
              className={custom.input}
              id="filled-secondary"
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={(input) => {
                fee_input = input;
              }}
              label={<Trans>Fee</Trans>}
            />
          </Box>
          <Box>
            <Button
              onClick={create}
              className={custom.send}
              variant="contained"
              color="primary"
            >
              <Trans>Create</Trans>
            </Button>
            <Backdrop className={custom.backdrop} open={open} invisible={false}>
              <CircularProgress color="inherit" />
            </Backdrop>
          </Box>
        </Box>
      </div>
      <Backdrop className={classes.backdrop} open={pending && created}>
        <CircularProgress color="inherit" />
      </Backdrop>
    </div>
  );
};
