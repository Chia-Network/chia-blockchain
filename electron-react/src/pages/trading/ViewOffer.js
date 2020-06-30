import { useDispatch, useSelector } from "react-redux";
import React from "react";
import {
  Box,
  Typography,
  Grid,
  Paper,
  Button,
  CircularProgress
} from "@material-ui/core";
import { makeStyles } from "@material-ui/core/styles";
import {
  resetTrades,
  offerParsingName,
  parsingStarted
} from "../../modules/TradeReducer";
import { mojo_to_chia_string } from "../../util/chia";
import { parsingStatePending } from "../../modules/TradeReducer";
import {
  accept_trade_action,
  parse_trade_action
} from "../../modules/trade_messages";

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
    margin: theme.spacing(3)
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

export const DropView = () => {
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

    const offer_file_path = e.dataTransfer.files[0].path;
    const offer_name = offer_file_path.replace(/^.*[\\/]/, "");

    dispatch(offerParsingName(offer_name, offer_file_path));
    dispatch(parse_trade_action(offer_file_path));
    dispatch(parsingStarted());
  };
  const parsing_state = useSelector(state => state.trade_state.parsing_state);
  const parsing = parsing_state === parsingStatePending ? true : false;

  const progressStyle = parsing
    ? { visibility: "visible" }
    : { visibility: "hidden" };
  const textStyle = !parsing
    ? { visibility: "visible" }
    : { visibility: "hidden" };

  return (
    <Paper className={(classes.paper, classes.balancePaper)}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              View Offer
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div
            onDrop={e => handleDrop(e)}
            onDragOver={e => handleDragOver(e)}
            onDragEnter={e => handleDragEnter(e)}
            onDragLeave={e => handleDragLeave(e)}
            className={classes.dragContainer}
          >
            <Paper className={classes.drag} style={{ position: "relative" }}>
              <div className={classes.dragText} style={textStyle}>
                Drag and drop offer file
              </div>
              <div className={classes.circle} style={progressStyle}>
                <CircularProgress color="secondary" />
              </div>
            </Paper>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

export const OfferView = () => {
  const classes = useStyles();
  const offer = useSelector(state => state.trade_state.parsed_offer);
  const dispatch = useDispatch();
  const file_path = useSelector(state => state.trade_state.parsed_offer_path);

  function accept() {
    dispatch(accept_trade_action(file_path));
  }

  function decline() {
    dispatch(resetTrades());
  }

  return (
    <Paper className={(classes.paper, classes.balancePaper)}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              View Offer
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.tradeSubSection}>
            {Object.keys(offer).map(name => (
              <OfferRow name={name} amount={offer[name]}></OfferRow>
            ))}
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Grid container spacing={2}>
              <Grid item xs={6}>
                <Button
                  onClick={accept}
                  className={classes.saveButton}
                  variant="contained"
                  color="primary"
                >
                  Accept
                </Button>
              </Grid>
              <Grid item xs={6}>
                <Button
                  onClick={decline}
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

const OfferRow = props => {
  const name = props.name;
  const amount = props.amount;
  const side = amount < 0 ? "Sell" : "Buy";

  return (
    <Box display="flex" style={{ minWidth: "100%" }}>
      <Box flexGrow={1}>{side}</Box>
      <Box flexGrow={1}>{mojo_to_chia_string(amount)}</Box>
      <Box
        style={{
          marginRight: 10,
          width: "40%",
          textAlign: "right",
          overflowWrap: "break-word"
        }}
      >
        {name}
      </Box>
    </Box>
  );
};

export const OfferSwitch = () => {
  const show_offer = useSelector(state => state.trade_state.show_offer);

  if (show_offer) {
    return <OfferView></OfferView>;
  } else {
    return <DropView></DropView>;
  }
};
