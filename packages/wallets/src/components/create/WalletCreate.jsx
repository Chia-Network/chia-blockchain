import React from 'react';
import { Routes, Route } from 'react-router-dom';
import WalletCreateList from './WalletCreateList';
// import WalletDIDList from '../did/WalletDIDList';
import WalletCATList from '../cat/WalletCATList';
import WalletCATCreateSimple from '../cat/WalletCATCreateSimple';

/*
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
                <ArrowBackIosIcon> </ArrowBackIosIcon>
              </Button>
            </Box>
            <Box flexGrow={1} className={classes.title}>
              <Typography component="h6" variant="h6">
                <Trans>Rate Limited Options</Trans>
              </Typography>
            </Box>
          </Box>
        </div>
        <List>
          <ListItem button onClick={select_option_admin}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText primary={<Trans>Create admin wallet</Trans>} />
          </ListItem>
          <ListItem button onClick={select_option_user}>
            <ListItemIcon>
              <InvertColorsIcon />
            </ListItemIcon>
            <ListItemText primary={<Trans>Create user wallet</Trans>} />
          </ListItem>
        </List>
      </Grid>
    </Grid>
  );
};
*/

export default function WalletCreate() {
  return (
    <Routes>
      <Route element={<WalletCreateList />} index />
      {/*  
      <Route path="did" element={<WalletDIDList />} />
      */}
      <Route path="cat/*" element={<WalletCATList />} />
      <Route path="simple" element={<WalletCATCreateSimple />} />
    </Routes>
  );
}
