import React from "react";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import { withRouter } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
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
  get_address,
  send_transaction,
  farm_block
} from "../modules/message";
import ExpansionPanel from "@material-ui/core/ExpansionPanel";
import ExpansionPanelSummary from "@material-ui/core/ExpansionPanelSummary";
import ExpansionPanelDetails from "@material-ui/core/ExpansionPanelDetails";
import ExpandMoreIcon from "@material-ui/icons/ExpandMore";
import { mojo_to_chia_string, chia_to_mojo } from "../util/chia";
import { unix_to_short_date } from "../util/utils";
import { openDialog } from "../modules/dialogReducer";
import { Tooltip } from "@material-ui/core";
import HelpIcon from "@material-ui/icons/Help";
const config = require("../config");
const drawerWidth = 240;

const useStyles = makeStyles(theme => ({
  front: {
    zIndex: "100"
  },
  resultSuccess: {
    color: "green"
  },
  resultFailure: {
    color: "red"
  },
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
    marginTop: theme.spacing(2),
    padding: theme.spacing(2),
    display: "flex",
    overflow: "auto",
    flexDirection: "column"
  },
  fixedHeight: {
    height: 240
  },
  heading: {
    fontSize: theme.typography.pxToRem(15),
    fontWeight: theme.typography.fontWeightRegular
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
  },
  amountField: {
    paddingRight: 20
  }
}));

const BalanceCardSubSection = props => {
  const classes = useStyles();
  return (
    <Grid item xs={12}>
      <div className={classes.cardSubSection}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Typography variant="subtitle1">
              {props.title}
              {props.tooltip ? (
                <Tooltip title={props.tooltip}>
                  <HelpIcon
                    style={{ color: "#c8c8c8", fontSize: 12 }}
                  ></HelpIcon>
                </Tooltip>
              ) : (
                ""
              )}
            </Typography>
          </Box>
          <Box>
            <Typography variant="subtitle1">
              {mojo_to_chia_string(props.balance)} TXCH
            </Typography>
          </Box>
        </Box>
      </div>
    </Grid>
  );
};

const BalanceCard = props => {
  var id = props.wallet_id;
  const balance = useSelector(
    state => state.wallet_state.wallets[id].balance_total
  );
  var balance_spendable = useSelector(
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
  const balance_ptotal = balance + balance_pending;
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
          tooltip="This is the total amount of Chia in the blockchain at the LCA block (latest common ancestor) that is controlled by your private keys. It includes frozen farming rewards, but not pending incoming and outgoing transactions."
        />
        <BalanceCardSubSection
          title="Spendable Balance"
          balance={balance_spendable}
          tooltip={
            "This is the amount of Chia that you can currently use to make transactions. It does not include pending farming rewards, pending incoming transctions, and Chia that you have just spent but is not yet in the blockchain."
          }
        />
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <ExpansionPanel className={classes.front}>
                  <ExpansionPanelSummary
                    expandIcon={<ExpandMoreIcon />}
                    aria-controls="panel1a-content"
                    id="panel1a-header"
                  >
                    <Typography className={classes.heading}>
                      View pending balances
                    </Typography>
                  </ExpansionPanelSummary>
                  <ExpansionPanelDetails>
                    <Grid container spacing={0}>
                      <BalanceCardSubSection
                        title="Pending Total Balance"
                        balance={balance_ptotal}
                        tooltip={
                          "This is the total balance + pending balance: it it what your balance will be after all pending transactions are confirmed."
                        }
                      />
                      <BalanceCardSubSection
                        title="Pending Balance"
                        balance={balance_pending}
                        tooltip={
                          "This is the sum of the incoming and outgoing pending transactions (not yet included into the blockchain). This does not include farming rewards."
                        }
                      />
                      <BalanceCardSubSection
                        title="Pending Farming Rewards"
                        balance={balance_frozen}
                        tooltip={
                          "This is the total amount of farming rewards farmed recently, that have been confirmed but are not yet spendable. Farming rewards are frozen for 200 blocks."
                        }
                      />
                      <BalanceCardSubSection
                        title="Pending Change"
                        balance={balance_change}
                        tooltip={
                          "This is the pending change, which are change coins which you have sent to yourself, but have not been confirmed yet."
                        }
                      />
                    </Grid>
                  </ExpansionPanelDetails>
                </ExpansionPanel>
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
  var fee_input = null;
  const dispatch = useDispatch();

  const sending_transaction = useSelector(
    state => state.wallet_state.wallets[id].sending_transaction
  );

  const send_transaction_result = useSelector(
    state => state.wallet_state.wallets[id].send_transaction_result
  );

  result = get_transaction_result(send_transaction_result);
  let result_message = result.message;
  let result_class = result.success ? classes.resultSuccess : classes.resultFailure;

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
    let address = address_input.value.trim();
    if (
      amount_input.value === "" ||
      Number(amount_input.value) === 0 ||
      !Number(amount_input.value) ||
      isNaN(Number(amount_input.value))
    ) {
      dispatch(openDialog("Please enter a valid numeric amount"));
      return;
    }
    if (fee_input.value === "" || isNaN(Number(fee_input.value))) {
      dispatch(openDialog("Please enter a valid numeric fee"));
      return;
    }
    const amount = chia_to_mojo(amount_input.value);
    const fee = chia_to_mojo(fee_input.value);

    if (address.includes("colour")) {
      dispatch(
        openDialog(
          "Error: Cannot send chia to coloured address. Please enter a chia address."
        )
      );
      return;
    } else if (address.substring(0, 12) === "chia_addr://") {
      address = address.substring(12);
    }
    if (address.startsWith("0x") || address.startsWith("0X")) {
      address = address.substring(2);
    }

    const amount_value = parseFloat(Number(amount));
    const fee_value = parseFloat(Number(fee));

    dispatch(send_transaction(id, amount_value, fee_value, address));
    address_input.value = "";
    amount_input.value = "";
    fee_input.value = "";
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
                  disabled={sending_transaction}
                  inputRef={input => {
                    address_input = input;
                  }}
                  label="Address / Puzzle hash"
                />
              </Box>
              <Box></Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={6}>
                <TextField
                  id="filled-secondary"
                  variant="filled"
                  color="secondary"
                  fullWidth
                  disabled={sending_transaction}
                  className={classes.amountField}
                  margin="normal"
                  inputRef={input => {
                    amount_input = input;
                  }}
                  label="Amount"
                />
              </Box>
              <Box flexGrow={6}>
                <TextField
                  id="filled-secondary"
                  variant="filled"
                  fullWidth
                  color="secondary"
                  margin="normal"
                  disabled={sending_transaction}
                  inputRef={input => {
                    fee_input = input;
                  }}
                  label="Fee"
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
                  style={config.local_test ? {} : { visibility: "hidden" }}
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
                  disabled={sending_transaction}
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
  const confirmed_to_string = tx => {
    return tx.confirmed
      ? "Confirmed at height " + tx.confirmed_at_index
      : "Pending";
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
              key={
                tx.to_address +
                tx.created_at_time +
                tx.amount +
                (tx.removals.length > 0 ? tx.removals[0].parent_coin_info : "")
              }
            >
              <TableCell className={classes.cell_short}>
                {incoming_string(tx.incoming)}
              </TableCell>
              <TableCell
                style={{ maxWidth: "150px" }}
                className={classes.cell_short}
              >
                {tx.to_address}
              </TableCell>
              <TableCell className={classes.cell_short}>
                {unix_to_short_date(tx.created_at_time)}
              </TableCell>
              <TableCell className={classes.cell_short}>
                {confirmed_to_string(tx)}
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
  const address = useSelector(
    state => state.wallet_state.wallets[id].address
  );
  const classes = useStyles();
  const dispatch = useDispatch();

  function newAddress() {
    dispatch(get_address(id));
  }

  function copy() {
    navigator.clipboard.writeText(address);
  }

  return (
    <Paper className={classes.paper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Receive Address
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
                  value={address}
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

export default withRouter(StandardWallet);
