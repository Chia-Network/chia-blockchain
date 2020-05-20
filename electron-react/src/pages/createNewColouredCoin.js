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
  CREATE_CC_WALLET_OPTIONS
} from "../modules/createWalletReducer";
import { useDispatch, useSelector } from "react-redux";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { useStyles } from "./CreateWallet";
import { create_coloured_coin } from "../modules/message";
import { chia_to_mojo } from "../util/chia";

export const customStyles = makeStyles(theme => ({
  input: {
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
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
  }
}));

export const CreateNewCCWallet = () => {
  const classes = useStyles();
  const custom = customStyles();
  const dispatch = useDispatch();
  var amount_input = null;
  var pending = useSelector(state => state.create_options.pending);
  var created = useSelector(state => state.create_options.created);

  function goBack() {
    dispatch(changeCreateWallet(CREATE_CC_WALLET_OPTIONS));
  }

  function create() {
    dispatch(createState(true, true));
    var amount = chia_to_mojo(amount_input.value);
    dispatch(create_coloured_coin(amount));
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
              Generate New Colour
            </Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.card}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              className={custom.input}
              fullWidth
              inputRef={input => {
                amount_input = input;
              }}
              label="Amount"
              variant="outlined"
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
