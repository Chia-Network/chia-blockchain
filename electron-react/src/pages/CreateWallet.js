import React from "react";
import {
  makeStyles,
  Typography,
  Paper,
  List,
  Button,
  Box
} from "@material-ui/core";
import ListItem from "@material-ui/core/ListItem";
import ListItemIcon from "@material-ui/core/ListItemIcon";
import ListItemText from "@material-ui/core/ListItemText";

import {
  changeCreateWallet,
  ALL_OPTIONS,
  CREATE_CC_WALLET_OPTIONS,
  CRAETE_EXISTING_CC,
  CREATE_NEW_CC
} from "../modules/createWalletReducer";
import { useDispatch, useSelector } from "react-redux";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { CreateNewCCWallet } from "./createNewColouredCoin";
import { CreateExistingCCWallet } from "./createExistingColouredCoin";
import InvertColorsIcon from "@material-ui/icons/InvertColors";

export const useStyles = makeStyles(theme => ({
  root: {
    display: "flex",
    paddingLeft: "0px",
    color: "#000000"
  },
  appBarSpacer: theme.mixins.toolbar,
  content: {
    flexGrow: 1,
    height: "100vh",
    overflow: "auto"
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0)
  },
  paper: {
    marginTop: theme.spacing(2),
    padding: theme.spacing(0),
    display: "flex",
    overflow: "auto",
    flexDirection: "column",
    minWidth: "100%"
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1)
  },
  title: {
    paddingTop: 6
  },
  sendButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
    height: 50
  },
  backdrop: {
    zIndex: 3000,
    color: "#fff"
  }
}));

export const MainWalletList = () => {
  const dispatch = useDispatch();
  const classes = useStyles();

  function select_option() {
    dispatch(changeCreateWallet(CREATE_CC_WALLET_OPTIONS));
  }

  return (
    <div>
      <div className={classes.cardTitle}>
        <Typography component="h6" variant="h6">
          Select Wallet Type
        </Typography>
      </div>
      <List>
        <ListItem button onClick={select_option}>
          <ListItemIcon>
            <InvertColorsIcon />
          </ListItemIcon>
          <ListItemText primary="Coloured Coin" />
        </ListItem>
      </List>
    </div>
  );
};

export const CCListItems = () => {
  const classes = useStyles();
  const dispatch = useDispatch();

  function goBack() {
    dispatch(changeCreateWallet(ALL_OPTIONS));
  }

  function select_option_new() {
    dispatch(changeCreateWallet(CREATE_NEW_CC));
  }

  function select_option_existing() {
    dispatch(changeCreateWallet(CRAETE_EXISTING_CC));
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
              Coloured Coin Options
            </Typography>
          </Box>
        </Box>
      </div>
      <List>
        <ListItem button onClick={select_option_new}>
          <ListItemIcon>
            <InvertColorsIcon />
          </ListItemIcon>
          <ListItemText primary="Create new coloured coin" />
        </ListItem>
        <ListItem button onClick={select_option_existing}>
          <ListItemIcon>
            <InvertColorsIcon />
          </ListItemIcon>
          <ListItemText primary="Create wallet for existing colour" />
        </ListItem>
      </List>
    </div>
  );
};

const CreateViewSwitch = () => {
  const view = useSelector(state => state.create_options.view);

  if (view === ALL_OPTIONS) {
    return <MainWalletList></MainWalletList>;
  } else if (view === CREATE_CC_WALLET_OPTIONS) {
    return <CCListItems></CCListItems>;
  } else if (view === CREATE_NEW_CC) {
    return <CreateNewCCWallet></CreateNewCCWallet>;
  } else if (view === CRAETE_EXISTING_CC) {
    return <CreateExistingCCWallet></CreateExistingCCWallet>;
  }
};

export const CreateWalletView = () => {
  const classes = useStyles();

  return (
    <div className={classes.root}>
      <Paper className={classes.paper}>
        <CreateViewSwitch></CreateViewSwitch>
      </Paper>
    </div>
  );
};
