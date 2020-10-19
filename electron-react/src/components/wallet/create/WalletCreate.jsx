import React from 'react';
import { Trans } from '@lingui/macro';
import {
  makeStyles,
  Typography,
  Grid,
  List,
  Button,
  Box,
  ListItem,
  ListItemIcon,
  ListItemText,
  Card,
  CardContent,
} from '@material-ui/core';
import { useDispatch, useSelector } from 'react-redux';
import {
  ArrowBackIos as ArrowBackIosIcon,
  InvertColors as InvertColorsIcon,
} from '@material-ui/icons';
import {
  changeCreateWallet,
  ALL_OPTIONS,
  CREATE_CC_WALLET_OPTIONS,
  CREATE_EXISTING_CC,
  CREATE_NEW_CC,
  CREATE_RL_WALLET_OPTIONS,
  CREATE_RL_ADMIN,
  CREATE_RL_USER,
} from '../../../modules/createWallet';
import { CreateNewCCWallet } from './createNewColouredCoin';
import { CreateExistingCCWallet } from './createExistingColouredCoin';
import { CreateRLAdminWallet } from './createRLAdmin';
import { CreateRLUserWallet } from './createRLUser';

export const useStyles = makeStyles((theme) => ({
  walletContainer: {
    marginBottom: theme.spacing(5),
  },
  root: {
    display: 'flex',
    paddingLeft: '0px',
    color: '#000000',
  },
  appBarSpacer: theme.mixins.toolbar,
  content: {
    flexGrow: 1,
    height: '100vh',
    overflow: 'auto',
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
  },
  paper: {
    marginTop: theme.spacing(2),
    padding: theme.spacing(2),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
    minWidth: '100%',
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1),
  },
  title: {
    paddingTop: 6,
  },
  sendButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
    height: 50,
  },
  backdrop: {
    zIndex: 3000,
    color: '#fff',
  },
}));

export const MainWalletList = () => {
  const dispatch = useDispatch();
  const classes = useStyles();

  function select_option_cc() {
    dispatch(changeCreateWallet(CREATE_CC_WALLET_OPTIONS));
  }

  function select_option_rl() {
    dispatch(changeCreateWallet(CREATE_RL_WALLET_OPTIONS));
  }

  return (
    <Grid container spacing={0}>
      <Grid item xs={12}>
        <div className={classes.cardTitle}>
          <Box display="flex">
            <Box flexGrow={1} className={classes.title}>
              <Typography component="h6" variant="h6">
                <Trans id="MainWalletList.title">Select Wallet Type</Trans>
              </Typography>
            </Box>
          </Box>
        </div>
        <List>
          <ListItem button onClick={select_option_cc}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText
              primary={
                <Trans id="MainWalletList.colouredCoin">Coloured Coin</Trans>
              }
            />
          </ListItem>
          <ListItem button onClick={select_option_rl}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText
              primary={
                <Trans id="MainWalletList.rateLimited">Rate Limited</Trans>
              }
            />
          </ListItem>
        </List>
      </Grid>
    </Grid>
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
    dispatch(changeCreateWallet(CREATE_EXISTING_CC));
  }

  return (
    <Grid container spacing={0}>
      <Grid item xs={12}>
        <div className={classes.cardTitle}>
          <Box display="flex">
            <Box>
              <Button onClick={goBack}>
                <ArrowBackIosIcon> </ArrowBackIosIcon>
              </Button>
            </Box>
            <Box flexGrow={1} className={classes.title}>
              <Typography component="h6" variant="h6">
                <Trans id="CCListItems.title">Coloured Coin Options</Trans>
              </Typography>
            </Box>
          </Box>
        </div>
        <List>
          <ListItem button onClick={select_option_new}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText
              primary={
                <Trans id="MainWalletList.createNewColouredCoin">
                  Create new coloured coin
                </Trans>
              }
            />
          </ListItem>
          <ListItem button onClick={select_option_existing}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText
              primary={
                <Trans id="MainWalletList.createWalletForExistingColour">
                  Create wallet for existing colour
                </Trans>
              }
            />
          </ListItem>
        </List>
      </Grid>
    </Grid>
  );
};

export const RLListItems = () => {
  const classes = useStyles();
  const dispatch = useDispatch();

  function goBack() {
    dispatch(changeCreateWallet(ALL_OPTIONS));
  }

  function select_option_admin() {
    dispatch(changeCreateWallet(CREATE_RL_ADMIN));
  }

  function select_option_user() {
    dispatch(changeCreateWallet(CREATE_RL_USER));
  }

  return (
    <Grid container spacing={0}>
      <Grid item xs={12}>
        <div className={classes.cardTitle}>
          <Box display="flex">
            <Box>
              <Button onClick={goBack}>
                <ArrowBackIosIcon />
              </Button>
            </Box>
            <Box flexGrow={1} className={classes.title}>
              <Typography component="h6" variant="h6">
                <Trans id="RLListItems.title">Rate Limited Options</Trans>
              </Typography>
            </Box>
          </Box>
        </div>
        <List>
          <ListItem button onClick={select_option_admin}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText
              primary={
                <Trans id="MainWalletList.createAdminWallet">
                  Create admin wallet
                </Trans>
              }
            />
          </ListItem>
          <ListItem button onClick={select_option_user}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText
              primary={
                <Trans id="MainWalletList.createUserWallet">
                  Create user wallet
                </Trans>
              }
            />
          </ListItem>
        </List>
      </Grid>
    </Grid>
  );
};

export function CreateWalletView() {
  const view = useSelector((state) => state.create_options.view);

  return (
    <Card>
      <CardContent>
        {view === ALL_OPTIONS && <MainWalletList />}
        {view === CREATE_CC_WALLET_OPTIONS && <CCListItems />}
        {view === CREATE_NEW_CC && <CreateNewCCWallet />}
        {view === CREATE_EXISTING_CC && <CreateExistingCCWallet />}
        {view === CREATE_RL_WALLET_OPTIONS && <RLListItems />}
        {view === CREATE_RL_ADMIN && <CreateRLAdminWallet />}
        {view === CREATE_RL_USER && <CreateRLUserWallet />}
      </CardContent>
    </Card>
  );
}
