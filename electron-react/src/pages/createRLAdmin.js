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
} from "../modules/createWallet";
import { useDispatch, useSelector } from "react-redux";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { useStyles } from "./CreateWallet";
import { create_rl_admin_action } from "../modules/message";
import { chia_to_mojo } from "../util/chia";
import { openDialog } from "../modules/dialog";

export const customStyles = makeStyles(theme => ({
  input: {
    marginLeft: theme.spacing(3),
    height: 56
  },
  inputLeft: {
    marginLeft: theme.spacing(3),
    height: 56
  },
  inputRight: {
    marginRight: theme.spacing(3),
    marginLeft: theme.spacing(6),
    height: 56
  },
  send: {
    paddingLeft: "0px",
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),
    height: 56,
    width: 150
  },
  card: {
    paddingTop: theme.spacing(10),
    height: 200
  },
  topCard: {
    height: 100
  },
  subCard: {
    height: 100
  },
  topTitleCard: {
    paddingTop: theme.spacing(6),
    paddingBottom: theme.spacing(1)
  },
  titleCard: {
    paddingBottom: theme.spacing(1)
  },
  inputTitleLeft: {
    marginLeft: theme.spacing(3),
    width: "50%"
  },
  inputTitleRight: {
    marginLeft: theme.spacing(3),
    width: "50%"
  }
}));

export const CreateRLAdminWallet = () => {
  const classes = useStyles();
  const custom = customStyles();
  const dispatch = useDispatch();
  var interval_input = null;
  var chiaper_input = null;
  var userpubkey_input = null;
  var amount_input = null;
  var fee_input = null;
  var pending = useSelector(state => state.create_options.pending);
  var created = useSelector(state => state.create_options.created);

  function goBack() {
    dispatch(changeCreateWallet(CREATE_RL_WALLET_OPTIONS));
  }

  function create() {
    if (
      interval_input.value === "" ||
      Number(interval_input.value) === 0 ||
      !Number(interval_input.value) ||
      isNaN(Number(interval_input.value))
    ) {
      dispatch(openDialog("Please enter a valid numeric interval length"));
      return;
    }
    if (
      chiaper_input.value === "" ||
      Number(chiaper_input.value) === 0 ||
      !Number(chiaper_input.value) ||
      isNaN(Number(chiaper_input.value))
    ) {
      dispatch(openDialog("Please enter a valid numeric spendable amount"));
      return;
    }
    if (userpubkey_input.value === "") {
      dispatch(openDialog("Please enter a valid pubkey"));
      return;
    }
    if (
      amount_input.value === "" ||
      Number(amount_input.value) === 0 ||
      !Number(amount_input.value) ||
      isNaN(Number(amount_input.value))
    ) {
      dispatch(openDialog("Please enter a valid initial coin amount"));
      return;
    }
    if (fee_input.value === "" || isNaN(Number(fee_input.value))) {
      dispatch(openDialog("Please enter a valid numeric fee"));
      return;
    }
    dispatch(createState(true, true));
    const interval = interval_input.value;
    const interval_value = parseInt(Number(interval));
    const chiaper = chia_to_mojo(chiaper_input.value);
    const chiaper_value = parseInt(Number(chiaper));
    const userpubkey = userpubkey_input.value;
    const amount = chia_to_mojo(amount_input.value);
    const amount_value = parseInt(Number(amount));
    // var fee = chia_to_mojo(fee_input.value);
    // TODO(lipa): send fee to server
    // const fee_value = parseInt(Number(fee));
    dispatch(
      create_rl_admin_action(
        interval_value,
        chiaper_value,
        userpubkey,
        amount_value
      )
    );
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
              Create Rate Limited Admin Wallet
            </Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.topTitleCard}>
        <Box display="flex">
          <Box flexGrow={6} className={custom.inputTitleLeft}>
            <Typography variant="subtitle1">
              Spending Interval Length (number of blocks)
            </Typography>
          </Box>
          <Box flexGrow={6} className={custom.inputTitleRight}>
            <Typography variant="subtitle1">
              Spendable Amount Per Interval
            </Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.topCard}>
        <Box display="flex">
          <Box flexGrow={6}>
            <TextField
              className={custom.inputLeft}
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={input => {
                interval_input = input;
              }}
              label="Interval"
            />
          </Box>
          <Box flexGrow={6}>
            <TextField
              className={custom.inputRight}
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={input => {
                chiaper_input = input;
              }}
              label="Spendable Amount"
            />
          </Box>
        </Box>
      </div>
      <div className={custom.titleCard}>
        <Box display="flex">
          <Box flexGrow={6} className={custom.inputTitleLeft}>
            <Typography variant="subtitle1">Amount For Initial Coin</Typography>
          </Box>
          <Box flexGrow={6} className={custom.inputTitleRight}>
            <Typography variant="subtitle1">Fee</Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.subCard}>
        <Box display="flex">
          <Box flexGrow={6}>
            <TextField
              className={custom.inputLeft}
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={input => {
                amount_input = input;
              }}
              label="Initial Amount"
            />
          </Box>
          <Box flexGrow={6}>
            <TextField
              className={custom.inputRight}
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={input => {
                fee_input = input;
              }}
              label="Fee"
            />
          </Box>
        </Box>
      </div>
      <div className={custom.titleCard}>
        <Box display="flex">
          <Box flexGrow={6} className={custom.inputTitleLeft}>
            <Typography variant="subtitle1">User Pubkey</Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.subCard}>
        <Box display="flex">
          <Box flexGrow={6}>
            <TextField
              className={custom.input}
              variant="filled"
              color="secondary"
              fullWidth
              inputRef={input => {
                userpubkey_input = input;
              }}
              label="Pubkey"
            />
          </Box>
          <Box>
            <Button
              onClick={create}
              className={custom.send}
              variant="contained"
              color="primary"
            >
              Create
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
