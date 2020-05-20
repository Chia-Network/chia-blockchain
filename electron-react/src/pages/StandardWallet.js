import React from "react";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import { withRouter } from "react-router-dom";
import { connect, useDispatch, useSelector } from "react-redux";
import Typography from "@material-ui/core/Typography";
import Paper from "@material-ui/core/Paper";
import Box from "@material-ui/core/Box";
import TextField from "@material-ui/core/TextField";
import Button from "@material-ui/core/Button";
import Table from "@material-ui/core/Table";
import TableBody from "@material-ui/core/TableBody";
import TableCell from "@material-ui/core/TableCell";

import TableHead from "@material-ui/core/TableHead";
import TableRow from "@material-ui/core/TableRow";
import {
  get_puzzle_hash,
  send_transaction,
  farm_block
} from "../modules/message";
import { mojo_to_chia_string, chia_to_mojo } from "../util/chia";
import { unix_to_short_date } from "../util/utils";
import { StatusCard } from "./Wallets";
import Accordion from "../components/Accordion";
import LockIcon from "@material-ui/icons/Lock";

const drawerWidth = 240;

const useStyles = makeStyles(theme => ({
  root: {
    display: "flex",
    paddingLeft: "0px"
  },
  toolbar: {
    paddingRight: 24 // keep right padding when drawer closed
  },
  toolbarIcon: {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    padding: "0 8px",
    ...theme.mixins.toolbar
  },
  appBar: {
    zIndex: theme.zIndex.drawer + 1,
    transition: theme.transitions.create(["width", "margin"], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen
    })
  },
  appBarShift: {
    marginLeft: drawerWidth,
    width: `calc(100% - ${drawerWidth}px)`,
    transition: theme.transitions.create(["width", "margin"], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
    })
  },
  menuButton: {
    marginRight: 36
  },
  menuButtonHidden: {
    display: "none"
  },
  title: {
    flexGrow: 1
  },
  drawerPaper: {
    position: "relative",
    whiteSpace: "nowrap",
    width: drawerWidth,
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
    })
  },
  drawerPaperClose: {
    overflowX: "hidden",
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen
    }),
    width: theme.spacing(7),
    [theme.breakpoints.up("sm")]: {
      width: theme.spacing(9)
    }
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
    padding: theme.spacing(0),
    display: "flex",
    overflow: "auto",
    flexDirection: "column"
  },
  fixedHeight: {
    height: 240
  },
  drawerWallet: {
    position: "relative",
    whiteSpace: "nowrap",
    width: drawerWidth,
    height: "100%",
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
    })
  },
  balancePaper: {
    height: 200,
    marginTop: theme.spacing(2)
  },
  sendCard: {
    marginTop: theme.spacing(2)
  },
  sendButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
    height: 50
  },
  copyButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(0),
    width: 50,
    height: 56
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1)
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1)
  },
  walletContainer: {
    marginBottom: theme.spacing(5)
  },
  table_root: {
    width: "100%",
    maxHeight: 600,
    overflowY: "scroll"
  },
  table: {
    height: "100%",
    overflowY: "scroll"
  },
  tableBody: {
    height: "100%",
    overflowY: "scroll"
  },
  row: {
    width: 700
  },
  cell_short: {
    fontSize: "14px",
    width: 50,
    overflowWrap: "break-word" /* Renamed property in CSS3 draft spec */
  }
}));

const BalanceCard = props => {
  var id = props.wallet_id;
  const balance = useSelector(
    state => state.wallet_state.wallets[id].balance_total
  );
  const balance_spendable = useSelector(
    state => state.wallet_state.wallets[id].balance_spendable
  );
  const balance_pending = useSelector(
    state => state.wallet_state.wallets[id].balance_pending
  );
  const balance_frozen = useSelector(
    state => state.wallet_state.wallets[id].balance_frozen
  );
  const balance_change = useSelector(
    state => state.wallet_state.wallets[id].balance_change
  );

  const classes = useStyles();

  const balancebox_1 = "<table width='100%'>";
  const balancebox_2 = "<tr><td align='left'>";
  const balancebox_3 = "</td><td align='right'>";
  const balancebox_4 = "</td></tr>";
  const balancebox_row = "<tr height='8px'></tr>";
  const balancebox_5 = "</td></tr></table>";
  const balancebox_pending = "Pending Total Balance";
  const balancebox_frozen = "Pending Farming Rewards";
  const balancebox_change = "Pending Change";
  const balancebox_xch = " XCH";
  const balance_pending_chia = mojo_to_chia_string(balance_pending);
  const balance_frozen_chia = mojo_to_chia_string(balance_frozen);
  const balance_change_chia = mojo_to_chia_string(balance_change);
  const acc_content =
    balancebox_1 +
    balancebox_2 +
    balancebox_pending +
    balancebox_3 +
    balance_pending_chia +
    balancebox_xch +
    balancebox_4 +
    balancebox_row +
    balancebox_2 +
    balancebox_frozen +
    balancebox_3 +
    balance_frozen_chia +
    balancebox_xch +
    balancebox_4 +
    balancebox_row +
    balancebox_2 +
    balancebox_change +
    balancebox_3 +
    balance_change_chia +
    balancebox_xch +
    balancebox_5;

  return (
    <Paper className={(classes.paper, classes.balancePaper)}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Balance
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <Typography variant="subtitle1">Total Balance</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle1">
                  {mojo_to_chia_string(balance)} XCH
                </Typography>
              </Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <Typography variant="subtitle1">Spendable Balance</Typography>
              </Box>
              <Box>
                <Typography alignRight variant="subtitle1">
                  {mojo_to_chia_string(balance_spendable, "mojo")} XCH
                </Typography>
              </Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <Accordion
                  title="View pending balances..."
                  content={acc_content}
                />
              </Box>
            </Box>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const SendCard = props => {
  var id = props.wallet_id;
  const classes = useStyles();
  var address_input = null;
  var amount_input = null;
  const dispatch = useDispatch();

  function farm() {
    var address = address_input.value;
    if (address !== "") {
      dispatch(farm_block(address));
    }
  }

  function send() {
    var address = address_input.value;
    var amount = chia_to_mojo(amount_input.value);
    if (address !== "" && amount !== "") {
      dispatch(send_transaction(id, amount, 0, address));
    }
  }

  return (
    <Paper className={(classes.paper, classes.sendCard)}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Create Transaction
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  fullWidth
                  inputRef={input => {
                    address_input = input;
                  }}
                  label="Address"
                  variant="outlined"
                />
              </Box>
              <Box></Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  fullWidth
                  inputRef={input => {
                    amount_input = input;
                  }}
                  label="Amount"
                  variant="outlined"
                />
              </Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <Button
                  onClick={farm}
                  className={classes.sendButton}
                  variant="contained"
                  color="primary"
                >
                  Farm
                </Button>
              </Box>
              <Box>
                <Button
                  onClick={send}
                  className={classes.sendButton}
                  variant="contained"
                  color="primary"
                >
                  Send
                </Button>
              </Box>
            </Box>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const HistoryCard = props => {
  var id = props.wallet_id;
  const classes = useStyles();
  return (
    <Paper className={(classes.paper, classes.sendCard)}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              History
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <TransactionTable wallet_id={id}> </TransactionTable>
        </Grid>
      </Grid>
    </Paper>
  );
};

const TransactionTable = props => {
  const classes = useStyles();
  var id = props.wallet_id;
  const transactions = useSelector(
    state => state.wallet_state.wallets[id].transactions
  );

  if (transactions.length === 0) {
    return <div style={{ margin: "30px" }}>No previous transactions</div>;
  }

  const incoming_string = incoming => {
    if (incoming) {
      return "Incoming";
    } else {
      return "Outgoing";
    }
  };
  const confirmed_to_string = confirmed => {
    return confirmed ? "Confirmed" : "Pending";
  };

  return (
    <Paper className={classes.table_root}>
      <Table stickyHeader className={classes.table}>
        <TableHead className={classes.head}>
          <TableRow className={classes.row}>
            <TableCell className={classes.cell_short}>Type</TableCell>
            <TableCell className={classes.cell_short}>To</TableCell>
            <TableCell className={classes.cell_short}>Date</TableCell>
            <TableCell className={classes.cell_short}>Status</TableCell>
            <TableCell className={classes.cell_short}>Amount</TableCell>
            <TableCell className={classes.cell_short}>Fee</TableCell>
          </TableRow>
        </TableHead>
        <TableBody className={classes.tableBody}>
          {transactions.map(tx => (
            <TableRow
              className={classes.row}
              key={tx.to_puzzle_hash + tx.created_at_time + tx.amount}
            >
              <TableCell className={classes.cell_short}>
                {incoming_string(tx.incoming)}
              </TableCell>
              <TableCell
                style={{ maxWidth: "150px" }}
                className={classes.cell_short}
              >
                {tx.to_puzzle_hash}
              </TableCell>
              <TableCell className={classes.cell_short}>
                {unix_to_short_date(tx.created_at_time)}
              </TableCell>
              <TableCell className={classes.cell_short}>
                {confirmed_to_string(tx.confirmed)}
              </TableCell>
              <TableCell className={classes.cell_short}>
                {mojo_to_chia_string(tx.amount)}
              </TableCell>
              <TableCell className={classes.cell_short}>
                {mojo_to_chia_string(tx.fee_amount)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Paper>
  );
};

const AddressCard = props => {
  var id = props.wallet_id;
  const puzzle_hash = useSelector(
    state => state.wallet_state.wallets[id].puzzle_hash
  );
  const classes = useStyles();
  const dispatch = useDispatch();

  function newAddress() {
    console.log("Dispatch for id: " + id);
    dispatch(get_puzzle_hash(id));
  }

  function copy() {
    navigator.clipboard.writeText(puzzle_hash);
  }

  return (
    <Paper className={(classes.paper, classes.sendCard)}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Receive Addresss
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  disabled
                  fullWidth
                  label="Address"
                  value={puzzle_hash}
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
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}></Box>
              <Box>
                <Button
                  onClick={newAddress}
                  className={classes.sendButton}
                  variant="contained"
                  color="primary"
                >
                  New Address
                </Button>
              </Box>
            </Box>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const StandardWallet = props => {
  const classes = useStyles();
  var id = props.wallet_id;
  const wallets = useSelector(state => state.wallet_state.wallets);

  return wallets.length > props.wallet_id ? (
    <Grid className={classes.walletContainer} item xs={12}>
      <BalanceCard wallet_id={id}></BalanceCard>
      <SendCard wallet_id={id}></SendCard>
      <AddressCard wallet_id={id}> </AddressCard>
      <HistoryCard wallet_id={id}></HistoryCard>
    </Grid>
  ) : (
    ""
  );
};

export default withRouter(connect()(StandardWallet));
