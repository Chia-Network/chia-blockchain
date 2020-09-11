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

import { did_spend } from "../modules/message";
import {
  Accordion,
  AccordionSummary,
  AccordionDetails
} from "@material-ui/core";
import ExpandMoreIcon from "@material-ui/icons/ExpandMore";
import { Tooltip } from "@material-ui/core";
import HelpIcon from "@material-ui/icons/Help";
import { mojo_to_chia_string, chia_to_mojo } from "../util/chia";

import { unix_to_short_date } from "../util/utils";

import { openDialog } from "../modules/dialogReducer";

const drawerWidth = 240;

const useStyles = makeStyles(theme => ({
  front: {
    zIndex: "100"
  },
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
    marginTop: theme.spacing(2),
    padding: theme.spacing(2),
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
  setupSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(3),
    paddingBottom: theme.spacing(1)
  },
  setupTitle: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(2),
    paddingBottom: theme.spacing(0)
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
  inputTitleLeft: {
    marginLeft: theme.spacing(0),
    marginBottom: theme.spacing(0),
    width: 400
  },
  inputTitleRight: {
    marginLeft: theme.spacing(3),
    width: 400
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
  leftField: {
    paddingRight: 20
  },
  submitButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
    height: 50
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
          tooltip=""
        />
        <BalanceCardSubSection
          title="Spendable Balance"
          balance={balance_spendable}
          tooltip={""}
        />
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <Accordion className={classes.front}>
                  <AccordionSummary
                    expandIcon={<ExpandMoreIcon />}
                    aria-controls="panel1a-content"
                    id="panel1a-header"
                  >
                    <Typography className={classes.heading}>
                      View pending balances
                    </Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Grid container spacing={0}>
                      <BalanceCardSubSection
                        title="Pending Total Balance"
                        balance={balance_ptotal}
                        tooltip={""}
                      />
                      <BalanceCardSubSection
                        title="Pending Balance"
                        balance={balance_pending}
                        tooltip={""}
                      />
                      <BalanceCardSubSection
                        title="Pending Change"
                        balance={balance_change}
                        tooltip={""}
                      />
                    </Grid>
                  </AccordionDetails>
                </Accordion>
              </Box>
            </Box>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const CashoutCard = props => {
  var id = props.wallet_id;
  var address_input = null;
  const classes = useStyles();
  const dispatch = useDispatch();

  function cashout() {
    let puzzlehash = address_input.value.trim();

    if (puzzlehash.startsWith("0x") || puzzlehash.startsWith("0X")) {
      puzzlehash = puzzlehash.substring(2);
    };

    dispatch(did_spend(id, puzzlehash));
    address_input.value = "";
  };

  return (
    <Paper className={classes.paper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Cash Out
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  variant="filled"
                  color="secondary"
                  fullWidth
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
              <Box>
                <Button
                  onClick={cashout}
                  className={classes.sendButton}
                  variant="contained"
                  color="primary"
                >
                  Cash Out
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

const DistributedIDWallet = props => {
  const classes = useStyles();
  var id = props.wallet_id;
  const wallets = useSelector(state => state.wallet_state.wallets);

  return wallets.length > props.wallet_id ? (
    <Grid className={classes.walletContainer} item xs={12}>
      <BalanceCard wallet_id={id}></BalanceCard>
      <CashoutCard wallet_id={id}></CashoutCard>
      <HistoryCard wallet_id={id}></HistoryCard>
    </Grid>
  ) : (
    ""
  );
};

export default withRouter(connect()(DistributedIDWallet));