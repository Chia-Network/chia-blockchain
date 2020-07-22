import React from "react";
import {
  makeStyles,
  Typography,
  Button,
  Box,
  TextField,
  Backdrop,
  CircularProgress
} from "@material-ui/core";

import {
  createState,
  changeCreateWallet,
  CREATE_RL_WALLET_OPTIONS
} from "../modules/createWalletReducer";
import { useDispatch, useSelector } from "react-redux";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { useStyles } from "./CreateWallet";
import { create_rl_user } from "../modules/message";
import { chia_to_mojo } from "../util/chia";
import { openDialog } from "../modules/dialogReducer";

export const customStyles = makeStyles(theme => ({
  topTitleCard: {
    paddingTop: theme.spacing(6),
    paddingBottom: theme.spacing(1)
  },
  input: {
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    paddingRight: theme.spacing(3),
    height: 56
  },
  inputTitleLeft: {
    marginLeft: theme.spacing(3),
    width: 400
  },
  send: {
    paddingLeft: "0px",
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),
    height: 56,
    width: 150
  },
  card: {
    height: 100
  },
  copyButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(0),
    width: 50,
    height: 56
  },
}));

export const CreateRLUserWallet = () => {
  const classes = useStyles();
  const custom = customStyles();
  const dispatch = useDispatch();
  const pubkey = useSelector(state => state.wallet_state.wallets[id].user_pubkey);

  function goBack() {
    dispatch(changeCreateWallet(CREATE_RL_WALLET_OPTIONS));
  }

  function copy() {
    navigator.clipboard.writeText(puzzle_hash);
  }

  function finish_setup() {
    dispatch(rl_set_user_info(wallet_id, interval, limit, origin_id, admin_pubkey))
  }

  return (
    <div>
      <div className={classes.cardTitle}>
        <Box display="flex">
          <Box>
            <Button onClick={goBack}>
              <ArrowBackIosIcon> </ArrowBackIosIcon>
            </Button>
          </Box>
          <Box flexGrow={1} className={classes.title}>
            <Typography component="h6" variant="h6">
              Set Up Rate Limited User Wallet
            </Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.card}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Typography variant="subtitle1">Initialize a Rate Limited User Wallet:</Typography>
          </Box>
          <Box flexGrow={1}>
            <TextField
              disabled
              fullWidth
              label="Pubkey"
              value={pubkey}
              variant="outlined"
            />
          </Box>
          <Box>
            <Button
              onClick={copy}
              className={classes.copyButton}
              variant="contained"
              color="secondary"
              disableElevation
            >
              Copy
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
