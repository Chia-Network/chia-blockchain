import { useDispatch, useSelector } from "react-redux";
import React from "react";
import {
  Box,
  Typography,
  Grid,
  Paper,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Button
} from "@material-ui/core";
import { makeStyles } from "@material-ui/core/styles";
import {
  newBuy,
  newSell,
  addTrade,
  resetTrades
} from "../../modules/TradeReducer";
import { chia_to_mojo, mojo_to_chia_string } from "../../util/chia";
import { openDialog } from "../../modules/dialogReducer";
import isElectron from "is-electron";
import { create_trade_offer } from "../../modules/message";
import { create_trade_action } from "../../modules/trade_messages";

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
  paper: {
    margin: theme.spacing(3),
    padding: theme.spacing(0),
    display: "flex",
    overflow: "auto",
    flexDirection: "column"
  },
  balancePaper: {
    marginTop: theme.spacing(2)
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
    marginBottom: theme.spacing(4)
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1)
  },
  tradeSubSection: {
    color: "#cccccc",
    borderRadius: 4,
    backgroundColor: "#555555",
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    marginTop: theme.spacing(1),
    padding: 15,
    overflowWrap: "break-word"
  },
  formControl: {
    widht: "100%"
  },
  input: {
    height: 56,
    width: "100%"
  },
  send: {
    marginLeft: theme.spacing(2),
    paddingLeft: "0px",
    height: 56,
    width: 150
  },
  card: {
    paddingTop: theme.spacing(10),
    height: 200
  },
  saveButton: {
    width: "100%",
    marginTop: theme.spacing(4),
    marginRight: theme.spacing(1),
    marginBottom: theme.spacing(2),
    height: 56
  },
  cancelButton: {
    width: "100%",
    marginTop: theme.spacing(4),
    marginLeft: theme.spacing(1),
    marginBottom: theme.spacing(2),
    height: 56
  },
  dragContainer: {
    paddingLeft: 20,
    paddingRight: 20,
    paddingBottom: 20
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
  },
  circle: {
    height: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center"
  }
}));

const TradeList = () => {
  const classes = useStyles();

  const trades = useSelector(state => state.trade_state.trades);
  const wallets = useSelector(state => state.wallet_state.wallets);

  return (
    <Grid item xs={12}>
      <div className={classes.tradeSubSection}>
        <Box display="flex" style={{ minWidth: "100%" }}>
          <Box flexGrow={1}>Side</Box>
          <Box flexGrow={1}>Amount</Box>
          <Box
            style={{
              marginRight: 10,
              width: "40%",
              textAlign: "right",
              overflowWrap: "break-word"
            }}
          >
            Colour
          </Box>
        </Box>
        {trades.map(trade => (
          <Box display="flex" style={{ minWidth: "100%" }}>
            <Box flexGrow={1}>{trade.side}</Box>
            <Box flexGrow={1}>{mojo_to_chia_string(trade.amount)}</Box>
            <Box
              style={{
                marginRight: 10,
                width: "40%",
                textAlign: "right",
                overflowWrap: "break-word"
              }}
            >
              {wallets[trade.wallet_id].name}
            </Box>
          </Box>
        ))}
      </div>
    </Grid>
  );
};

export const CreateOffer = () => {
  const wallets = useSelector(state => state.wallet_state.wallets);
  const classes = useStyles();
  const dispatch = useDispatch();
  var amount_input = null;
  var buy_or_sell = null;
  var wallet_id = null;
  const trades = useSelector(state => state.trade_state.trades);

  function add() {
    if (!wallet_id.value) {
      dispatch(openDialog("", "Please select coin type "));
      return;
    }
    if (amount_input.value === "") {
      dispatch(openDialog("", "Please select amount "));
      return;
    }
    if (!buy_or_sell.value) {
      dispatch(openDialog("", "Please select buy or sell "));
      return;
    }
    const mojo = chia_to_mojo(amount_input.value);
    var trade = null;
    if (buy_or_sell.value === 1) {
      trade = newBuy(mojo, wallet_id.value);
    } else {
      trade = newSell(mojo, wallet_id.value);
    }
    dispatch(addTrade(trade));
  }
  async function save() {
    console.log(trades.length);
    if (trades.length === 0) {
      dispatch(openDialog("", "Please add trade pair"));
      return;
    }
    if (isElectron()) {
      const dialogOptions = {};
      const result = await window.remote.dialog.showSaveDialog(dialogOptions);
      const { filePath } = result;
      const offer = {};
      for (var i = 0; i < trades.length; i++) {
        const trade = trades[i];
        if (trade.side === "buy") {
          offer[trade.wallet_id] = trade.amount;
        } else {
          offer[trade.wallet_id] = -trade.amount;
        }
      }
      dispatch(create_trade_action(offer, filePath));
    } else {
      dispatch(
        openDialog("", "This feature is available only from electron app")
      );
    }
  }
  function cancel() {
    dispatch(resetTrades());
  }

  return (
    <Paper className={classes.paper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Create Trade Offer
            </Typography>
          </div>
        </Grid>
        <TradeList></TradeList>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Grid container spacing={2}>
              <Grid item xs={6}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>Buy or Sell</InputLabel>
                  <Select
                    inputRef={input => {
                      buy_or_sell = input;
                    }}
                    label="Buy Or Sell"
                  >
                    <MenuItem value={1}>Buy</MenuItem>
                    <MenuItem value={2}>Sell</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={6}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>Colour</InputLabel>
                  <Select
                    inputRef={input => {
                      wallet_id = input;
                    }}
                    label="Colour"
                  >
                    {wallets.map(wallet => (
                      <MenuItem value={wallet.id}>{wallet.name}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Box display="flex">
              <Box flexGrow={1}>
                <TextField
                  className={classes.input}
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
                  onClick={add}
                  className={classes.send}
                  variant="contained"
                  color="primary"
                >
                  Add
                </Button>
              </Box>
            </Box>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Grid container spacing={2}>
              <Grid item xs={6}>
                <Button
                  onClick={save}
                  className={classes.saveButton}
                  variant="contained"
                  color="primary"
                >
                  Save
                </Button>
              </Grid>
              <Grid item xs={6}>
                <Button
                  onClick={cancel}
                  className={classes.cancelButton}
                  variant="contained"
                  color="primary"
                >
                  Cancel
                </Button>
              </Grid>
            </Grid>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};
