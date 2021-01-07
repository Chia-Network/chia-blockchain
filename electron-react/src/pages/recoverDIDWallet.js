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
  CREATE_DID_WALLET_OPTIONS
} from "../modules/createWalletReducer";
import { useDispatch, useSelector } from "react-redux";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { useStyles } from "./CreateWallet";
import { recover_did_wallet } from "../modules/message";
import { chia_to_mojo } from "../util/chia";
import { openDialog } from "../modules/dialogReducer";
import { useForm, Controller, useFieldArray } from "react-hook-form";

export const customStyles = makeStyles(theme => ({
  input: {
    marginLeft: theme.spacing(3),
    height: 56
  },
  inputLeft: {
    marginLeft: theme.spacing(3),
    width: "75%",
    height: 56
  },
  inputDIDs: {
    paddingTop: theme.spacing(3),
    marginLeft: theme.spacing(0)
  },
  inputDID: {
    marginLeft: theme.spacing(0),
    marginBottom: theme.spacing(2),
    width: "50%",
    height: 56
  },
  inputRight: {
    marginRight: theme.spacing(3),
    marginLeft: theme.spacing(6),
    height: 56
  },
  sendButton: {
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),
    height: 56,
    width: 150
  },
  addButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    height: 56,
    width: 50
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
    paddingTop: theme.spacing(3),
    marginLeft: theme.spacing(3),
    width: "50%"
  },
  inputTitleRight: {
    marginLeft: theme.spacing(3),
    width: "50%"
  },
  ul: {
    listStyle: "none"
  },
  sideButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(2),
    width: 50,
    height: 56
  }
}));

export const RecoverDIDWallet = () => {
  const classes = useStyles();
  const custom = customStyles();
  const dispatch = useDispatch();
  var backup_file_input = null;
  var pending = useSelector(state => state.create_options.pending);
  var created = useSelector(state => state.create_options.created);

  function goBack() {
    dispatch(changeCreateWallet(CREATE_DID_WALLET_OPTIONS));
  }

  function recover() {
    dispatch(createState(true, true));
    dispatch(recover_did_wallet());
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
              Recover Distributed Identity Wallet
            </Typography>
          </Box>
        </Box>
      </div>
      <div className={custom.titleCard}>
        <Box display="flex">
          <Box flexGrow={6} className={custom.inputTitleLeft}>
            <Typography variant="subtitle1">Backup File:</Typography>
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
                backup_file_input = input;
              }}
              label="Backup File"
            />
          </Box>
          <Box>
            <Button
              onClick={recover}
              className={custom.sendButton}
              variant="contained"
              color="primary"
            >
              Recover
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