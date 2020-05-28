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
  cc_spend,
  farm_block,
  rename_cc_wallet
} from "../modules/message";
import { mojo_to_chia_string, chia_to_mojo, mojo_to_colouredcoin_string } from "../util/chia";
import { unix_to_short_date } from "../util/utils";
import Accordion from "../components/Accordion";
import { openDialog } from "../modules/dialogReducer";
const config = require("../config");

const drawerWidth = 240;

const useStyles = makeStyles(theme => ({
  root: {
    display: "flex",
    paddingLeft: "0px"
  },
  resultSuccess: {
    color: "green"
  },
  resultFailure: {
    color: "red"
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
    padding: theme.spacing(1),
    margin: theme.spacing(1),
    marginBottom: theme.spacing(2),
    marginTop: theme.spacing(2),
    display: "flex",
    overflow: "auto",
    flexDirection: "column"
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
    width: 70,
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
    overflowY: "scroll",
    padding: theme.spacing(1),
    margin: theme.spacing(1),
    marginBottom: theme.spacing(2),
    marginTop: theme.spacing(2),
    display: "flex",
    overflow: "auto",
    flexDirection: "column"
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
  },
  colourCard: {
    overflowWrap: "break-word",
    marginTop: theme.spacing(2),
    paddingBottom: 20
  }
}));

const ColourCard = props => {
  var id = props.wallet_id;

  const dispatch = useDispatch();
  const colour = useSelector(state => state.wallet_state.wallets[id].colour);
  const name = useSelector(state => state.wallet_state.wallets[id].name);
  console.log(name);

  var name_input = null;

  function rename() {
    dispatch(rename_cc_wallet(id, name_input.value));
  }

  const classes = useStyles();
  return (
    <Paper className={classes.paper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Colour Info
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1} style={{ marginBottom: 20 }}>
                <Typography variant="subtitle1">Colour:</Typography>
              </Box>
              <Box
                style={{
                  paddingLeft: 20,
                  width: "80%",
                  overflowWrap: "break-word"
                }}
              >
                <Typography variant="subtitle1">{colour}</Typography>
              </Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  id="filled-secondary"
                  variant="filled"
                  color="secondary"
                  fullWidth
                  label="Nickname"
                  inputRef={input => {
                    name_input = input;
                  }}
                  defaultValue={name}
                  key={name}
                />
              </Box>
              <Box>
                <Button
                  onClick={rename}
                  className={classes.copyButton}
                  variant="contained"
                  color="secondary"
                  disableElevation
                >
                  Rename
                </Button>
              </Box>
            </Box>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const BalanceCardSubSection = props => {
  const classes = useStyles();
  var cc_unit = props.name;
  if (cc_unit.length > 10) {
    cc_unit = cc_unit.substring(0, 10) + "...";
  }
  return (
    <Grid item xs={12}>
      <div className={classes.cardSubSection}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Typography variant="subtitle1">{props.title}</Typography>
          </Box>
          <Box>
            <Typography variant="subtitle1">
              {mojo_to_colouredcoin_string(props.balance)} {cc_unit}
            </Typography>
          </Box>
        </Box>
      </div>
    </Grid>
  );
};

const BalanceCard = props => {
  var id = props.wallet_id;
  const name = useSelector(state => state.wallet_state.wallets[id].name);
  const balance = useSelector(
    state => state.wallet_state.wallets[id].balance_total
  );
  var balance_spendable = useSelector(
    state => state.wallet_state.wallets[id].balance_spendable
  );
  const balance_pending = useSelector(
    state => state.wallet_state.wallets[id].balance_pending
  );
  const balance_change = useSelector(
    state => state.wallet_state.wallets[id].balance_change
  );
  const balance_ptotal = balance + balance_pending;

  var cc_unit = name;
  if (cc_unit.length > 10) {
    cc_unit = cc_unit.substring(0, 10) + "...";
  }

  const balancebox_1 = "<table width='100%'>";
  const balancebox_2 = "<tr><td align='left'>";
  const balancebox_3 = "</td><td align='right'>";
  const balancebox_4 = "</td></tr>";
  const balancebox_row = "<tr height='8px'></tr>";
  const balancebox_5 = "</td></tr></table>";
  const balancebox_ptotal = "Pending Total Balance";
  const balancebox_pending = "Pending Transactions";
  const balancebox_change = "Pending Change";
  const balancebox_unit = " " + cc_unit;
  const balancebox_hline =
    "<tr><td colspan='2' style='text-align:center'><hr width='50%'></td></tr>";
  const balance_ptotal_chia = mojo_to_colouredcoin_string(balance_ptotal, "mojo");
  const balance_pending_chia = mojo_to_colouredcoin_string(balance_pending, "mojo");
  const balance_change_chia = mojo_to_colouredcoin_string(balance_change, "mojo");
  const acc_content =
    balancebox_1 +
    balancebox_2 +
    balancebox_ptotal +
    balancebox_3 +
    balance_ptotal_chia +
    balancebox_unit +
    balancebox_hline +
    balancebox_4 +
    balancebox_row +
    balancebox_2 +
    balancebox_pending +
    balancebox_3 +
    balance_pending_chia +
    balancebox_unit +
    balancebox_4 +
    balancebox_row +
    balancebox_2 +
    balancebox_change +
    balancebox_3 +
    balance_change_chia +
    balancebox_unit +
    balancebox_5;

  const classes = useStyles();
  return (
    <Paper className={classes.paper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Balance
            </Typography>
          </div>
        </Grid>
        <BalanceCardSubSection
          title="Total Balance"
          balance={balance}
          name={name}
        />
        <BalanceCardSubSection
          title="Spendable Balance"
          balance={balance_spendable}
          name={name}
        />
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

  const sending_transaction = useSelector(
    state => state.wallet_state.sending_transaction
  );

  const send_transaction_result = useSelector(
    state => state.wallet_state.send_transaction_result
  );

  const colour = useSelector(state => state.wallet_state.wallets[id].colour);

  let result_message = "";
  let result_class = classes.resultSuccess;
  if (send_transaction_result) {
    if (send_transaction_result.status === "SUCCESS") {
      result_message =
        "Transaction has successfully been sent to a full node and included in the mempool.";
    } else if (send_transaction_result.status === "PENDING") {
      result_message =
        "Transaction has sent to a full node and is pending inclusion into the mempool. " +
        send_transaction_result.reason;
    } else {
      result_message = "Transaction failed. " + send_transaction_result.reason;
      result_class = classes.resultFailure;
    }
  }

  function farm() {
    var address = address_input.value;
    if (address !== "") {
      dispatch(farm_block(address));
    }
  }

  function send() {
    if (sending_transaction) {
      return;
    }
    let puzzle_hash = address_input.value;
    const amount = chia_to_mojo(amount_input.value);

    if (
      puzzle_hash.includes("chia_addr") ||
      puzzle_hash.includes("colour_desc")
    ) {
      dispatch(
        openDialog(
          "Error: recipient address is not a coloured wallet address. Please enter a coloured wallet address"
        )
      );
      return;
    }
    if (puzzle_hash.substring(0, 14) === "colour_addr://") {
      const colour_id = puzzle_hash.substring(14, 78);
      puzzle_hash = puzzle_hash.substring(79);
      if (colour_id !== colour) {
        dispatch(
          openDialog(
            "Error the entered address appears to be for a different colour."
          )
        );
        return;
      }
    }

    if (puzzle_hash.startsWith("0x") || puzzle_hash.startsWith("0X")) {
      puzzle_hash = puzzle_hash.substring(2);
    }
    if (puzzle_hash.length !== 64) {
      dispatch(
        openDialog("Please enter a 32 byte puzzle hash in hexadecimal format")
      );
      return;
    }
    const amount_value = parseFloat(Number(amount));
    if (amount_value === 0 || !amount_value || isNaN(amount_value)) {
      dispatch(openDialog("Please enter a valid numeric amount"));
      return;
    }

    dispatch(cc_spend(id, puzzle_hash, amount_value));
    address_input.value = "";
    amount_input.value = "";
  }

  return (
    <Paper className={classes.paper}>
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
            <p className={result_class}>{result_message}</p>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  id="filled-secondary"
                  variant="filled"
                  color="secondary"
                  fullWidth
                  inputRef={input => {
                    address_input = input;
                  }}
                  label="Address"
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
                  id="filled-secondary"
                  variant="filled"
                  color="secondary"
                  fullWidth
                  inputRef={input => {
                    amount_input = input;
                  }}
                  label="Amount"
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
                  style={config.local_test ? {} : { visibility: "hidden" }}
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
    <Paper className={classes.paper}>
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
    // console.log("Dispatch for id: " + id);
    dispatch(get_puzzle_hash(id));
  }

  function copy() {
    navigator.clipboard.writeText(puzzle_hash);
  }

  return (
    <Paper className={classes.paper}>
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

const ColouredWallet = props => {
  const classes = useStyles();
  const id = useSelector(state => state.wallet_menu.id);
  const name = useSelector(state => state.wallet_state.wallets[id].name);
  const wallets = useSelector(state => state.wallet_state.wallets);

  return wallets.length > props.wallet_id ? (
    <Grid className={classes.walletContainer} item xs={12}>
      <ColourCard wallet_id={id} name={name}></ColourCard>
      <BalanceCard wallet_id={id}></BalanceCard>
      <SendCard wallet_id={id}></SendCard>
      <AddressCard wallet_id={id}></AddressCard>
      <HistoryCard wallet_id={id}></HistoryCard>
    </Grid>
  ) : (
    ""
  );
};

export default withRouter(connect()(ColouredWallet));
