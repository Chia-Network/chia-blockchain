import React from "react";
import {
  Typography,
  Paper,
  Grid,
  Button,
  Box,
  TextField,
  Backdrop,
  CircularProgress
} from "@material-ui/core";
import CssBaseline from "@material-ui/core/CssBaseline";
import Container from "@material-ui/core/Container";
import { makeStyles } from "@material-ui/core/styles";

import {
  createState,
  changeCreateWallet,
  CREATE_DID_WALLET_OPTIONS
} from "../modules/createWalletReducer";
import { useDispatch, useSelector } from "react-redux";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { useStyles } from "./CreateWallet";
import { recover_did_action } from "../modules/message";
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
  },
  root: {
    display: "flex",
    paddingLeft: "0px"
  },
  content: {
    flexGrow: 1,
    height: "calc(100vh - 64px)",
    overflowX: "hidden"
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
    paddingLeft: theme.spacing(0)
  },
  balancePaper: {
    margin: theme.spacing(3)
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(4)
  },
  dragContainer: {
    paddingLeft: 20,
    paddingRight: 20,
    paddingBottom: 20
  },
  dragBox: {
    height: 300,
    width: "100%",
    margin: theme.spacing(3)
  },
  drag: {
    backgroundColor: "#888888",
    height: 300,
    width: "100%"
  },
  dragText: {
    margin: 0,
    position: "absolute",
    top: "50%",
    left: "50%",
    transform: "translate(-50%, -50%)"
  }
}));

export const RecoverDIDWallet = () => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const handleDragEnter = e => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragLeave = e => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragOver = e => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDrop = e => {
    e.preventDefault();
    e.stopPropagation();

    const recovery_file_path = e.dataTransfer.files[0].path;
    const recovery_name = recovery_file_path.replace(/^.*[\\/]/, "");

    dispatch(recover_did_action(recovery_file_path));
  };
  function goBack() {
    dispatch(changeCreateWallet(CREATE_DID_WALLET_OPTIONS));
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
              View DID Recovery File
            </Typography>
          </Box>
        </Box>
      </div>
      <div>
        <Box flexGrow={1} className={classes.dragBox}>
          <div
            onDrop={e => handleDrop(e)}
            onDragOver={e => handleDragOver(e)}
            onDragEnter={e => handleDragEnter(e)}
            onDragLeave={e => handleDragLeave(e)}
            className={classes.dragContainer}
          >
            <Paper className={classes.drag}>
              <div className={classes.dragText}>
                Drag and drop offer file
              </div>
            </Paper>
          </div>
        </Box>
      </div>
    </div>
  );
};