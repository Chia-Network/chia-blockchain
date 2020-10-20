import { useDispatch, useSelector } from 'react-redux';
import React from 'react';
import { Trans } from '@lingui/macro';
import { makeStyles } from '@material-ui/core/styles';
import { Paper, Button, Tooltip, Divider, ListItem , Box, Typography } from '@material-ui/core';

import ArrowBackIosIcon from '@material-ui/icons/ArrowBackIos';
import Grid from '@material-ui/core/Grid';
import HelpIcon from '@material-ui/icons/Help';
import { unix_to_short_date } from '../../util/utils';
import { presetOverview, presentTrade } from '../../modules/trade';
import { mojo_to_chia_string } from '../../util/chia';
import {
  get_all_trades,
  cancel_trade_with_spend_action,
  cancel_trade_action,
} from '../../modules/trade_messages';

const useStyles = makeStyles((theme) => ({
  root: {
    display: 'flex',
    paddingLeft: '0px',
  },
  content: {
    flexGrow: 1,
    height: 'calc(100vh - 64px)',
    overflowX: 'hidden',
  },
  paper: {
    padding: theme.spacing(0),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
    margin: theme.spacing(3),
  },
  trade_table: {
    padding: theme.spacing(0),
  },
  pending_trades: {
    padding: theme.spacing(1),
  },
  empty: {
    backgroundColor: '#999999',
    height: 100,
    width: '100%',
  },
  centerText: {
    margin: 0,
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
  },
  accept: {
    paddingLeft: '0px',
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),
    marginBottom: theme.spacing(2),
    height: 56,
    width: 150,
  },
  trade_row: {
    cursor: 'pointer',
    borderBottom: '1px solid #eeeeee',
    /* mouse over link */
    height: 40,
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(4),
  },
  detail_items: {
    padding: theme.spacing(1),
    backgroundColor: '#eeeeee',
  },
  tradeSubSection: {
    color: '#000000',
    BorderRadiusBottomleft: 4,
    BorderRadiusBottomRight: 4,
    backgroundColor: '#eeeeee',
    marginBottom: theme.spacing(5),
    padding: 15,
    overflowWrap: 'break-word',
  },
}));

const TradeRow = (props) => {
  const {trade_id} = props.trade;
  const {status} = props.trade;
  const time = unix_to_short_date(props.trade.created_at_time);
  const classes = useStyles();
  const dispatch = useDispatch();

  function displayTrade() {
    console.log('Show this trade');
    dispatch(presentTrade(props.trade));
  }

  return (
    <ListItem button onClick={displayTrade}>
      <Box
        display="flex"
        style={{ minWidth: '100%' }}
        className={classes.trade_row}
      >
        <Box flexGrow={1}>{trade_id.slice(0, 16)}</Box>
        <Box flexGrow={1}>{status}</Box>
        <Box
          style={{
            marginRight: 10,
            textAlign: 'right',
            overflowWrap: 'break-word',
          }}
        >
          {time}
        </Box>
      </Box>
    </ListItem>
  );
};

export const TableHeader = () => {
  return (
    <Box display="flex" style={{ minWidth: '100%' }}>
      <Box flexGrow={1}>
        <Trans id="TradeOverviewTableHeader.tradeId">Trade ID</Trans>
      </Box>
      <Box flexGrow={1}>
        <Trans id="TradeOverviewTableHeader.status">Status</Trans>
      </Box>
      <Box
        style={{
          marginRight: 10,
          textAlign: 'right',
          overflowWrap: 'break-word',
        }}
      >
        <Trans id="TradeOverviewTableHeader.date">Date</Trans>
      </Box>
    </Box>
  );
};

export const TradeTable = (props) => {
  const {trades} = props;
  const classes = useStyles();

  if (trades.length === 0) {
    return (
      <div className={classes.trade_table}>
        <TableHeader />
        <Paper className={classes.empty} style={{ position: 'relative' }}>
          <div className={classes.centerText}>
            <Trans id="TradeOverviewTable.tradesShowUpHere">
              Trades will show up here
            </Trans>
          </div>
        </Paper>
      </div>
    );
  }
  return (
    <div className={classes.trade_table}>
      <TableHeader />
      {trades.map((trade) => (
        <TradeRow key={trade.trade_id} trade={trade} />
      ))}
    </div>
  );
};

const getDetailItems = (trade) => {
  const detail_items = [];
  const trade_id_item = {
    label: <Trans id="TradeDetail.tradeId">Trade ID:</Trans>,
    value: trade.trade_id.slice(0, 16),
    colour: 'black',
    tooltip: <Trans id="TradeDetail.tradeIdTooltip">Unique identifier</Trans>,
  };

  const status_item = {
    label: <Trans id="TradeDetail.status">Status:</Trans>,
    value: trade.status,
    colour: 'black',
    tooltip: <Trans id="TradeDetail.statusTooltip">Current trade status</Trans>,
  };

  const date_item = {
    label: <Trans id="TradeDetail.createdAt">Created At:</Trans>,
    value: unix_to_short_date(trade.created_at_time),
    colour: 'black',
    tooltip: (
      <Trans id="TradeDetail.createdAtTooltip">
        Time this trade was created at this time
      </Trans>
    ),
  };
  let confirmed_string = '';
  const confirmed = trade.confirmed_at_index;
  if (confirmed === 0) {
    confirmed_string = (
      <Trans id="TradeDetail.notConfirmedYet">Not confirmed yet</Trans>
    );
  } else {
    confirmed_string = trade.confirmed_at_index;
  }

  const executed_at_item = {
    label: <Trans id="TradeDetail.confirmedAtBlock">Confirmed at block:</Trans>,
    value: confirmed_string,
    colour: 'black',
    tooltip: (
      <Trans id="TradeDetail.confirmedAtBlockTooltip">
        This trade was included on blockchain at this block height
      </Trans>
    ),
  };
  let our = '';
  if (trade.my_offer === true) {
    our = <Trans id="TradeDetail.yes">Yes</Trans>;
  } else {
    our = <Trans id="TradeDetail.no">No</Trans>;
  }
  const offer_creator_item = {
    label: <Trans id="TradeDetail.createdByUs">Created by us:</Trans>,
    value: our,
    colour: 'black',
    tooltip: (
      <Trans id="TradeDetail.createdByUsTooltip">
        Indicated if this offer was created by us
      </Trans>
    ),
  };

  let accepted = '';
  const accepted_time = trade.accepted_at_time;

  if (accepted_time === null) {
    accepted = <Trans id="TradeDetail.notAcceptedYet">Not accepted yet</Trans>;
  } else {
    accepted = unix_to_short_date(trade.accepted_at_time);
  }

  const accepted_at_time = {
    label: <Trans id="TradeDetail.acceptedAtTime">Accepted at time:</Trans>,
    value: accepted,
    colour: 'black',
    tooltip: (
      <Trans id="TradeDetail.acceptedAtTimeTooltip">
        Indicated what time this offer was accepted
      </Trans>
    ),
  };

  detail_items.push(trade_id_item);
  detail_items.push(status_item);
  detail_items.push(date_item);
  detail_items.push(executed_at_item);
  detail_items.push(offer_creator_item);
  detail_items.push(accepted_at_time);

  return detail_items;
};

const DetailCell = (props) => {
  const classes = useStyles();
  const {item} = props;
  const {label} = item;
  const {value} = item;
  const {tooltip} = item;
  const {colour} = item;
  return (
    <Grid item xs={6}>
      <div className={classes.cardSubSection}>
        <Box display="flex">
          <Box display="flex" flexGrow={1}>
            <Typography>{label}</Typography>
            {tooltip ? (
              <Tooltip title={tooltip}>
                <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
              </Tooltip>
            ) : (
              ''
            )}
          </Box>
          <Box>
            <Typography>
              <span style={colour ? { color: colour } : {}}>{value}</span>
            </Typography>
          </Box>
        </Box>
      </div>
    </Grid>
  );
};

const OfferRow = (props) => {
  const {name} = props;
  const {amount} = props;
  const {trade} = props;
  let multiplier = 1;
  if (!trade) {
    multiplier = 1;
  } else if (trade.my_offer === true) {
      multiplier = -1;
    }

  const side =
    amount * multiplier < 0 ? (
      <Trans id="TradeOfferRow.sell">Sell</Trans>
    ) : (
      <Trans id="TradeOfferRow.buy">Buy</Trans>
    );

  return (
    <Box display="flex" style={{ minWidth: '100%' }}>
      <Box
        style={{
          marginRight: 10,
          width: '40%',
          textAlign: 'left',
          overflowWrap: 'break-word',
        }}
      >
        {name}
      </Box>
      <Box flexGrow={1}>{side}</Box>
      <Box flexGrow={1} style={{ textAlign: 'right' }}>
        {mojo_to_chia_string(amount)}
      </Box>
    </Box>
  );
};

export const TradeDetail = () => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const presented = useSelector((state) => state.trade_state.trade_showed);
  const {status} = presented;

  let visible = { visibility: 'visible' };
  if (
    status === 'Confirmed' ||
    status === 'Pending Cancelled' ||
    status === 'Cancelled'
  ) {
    visible = { visibility: 'hidden' };
  }
  function goBack() {
    dispatch(presetOverview());
  }

  function secure_cancel() {
    dispatch(cancel_trade_with_spend_action(presented.trade_id));
  }

  function cancel() {
    dispatch(cancel_trade_action(presented.trade_id));
  }

  const trade_detail_items = getDetailItems(presented);

  return (
    <Paper className={classes.paper}>
      <div className={classes.pending_trades}>
        <div className={classes.cardTitle}>
          <Box display="flex">
            <Box>
              <Button onClick={goBack}>
                <ArrowBackIosIcon> </ArrowBackIosIcon>
              </Button>
            </Box>
            <Box flexGrow={1} className={classes.title}>
              <Typography component="h6" variant="h6">
                <Trans id="TradeDetail.title">Trade Details</Trans>
              </Typography>
            </Box>
          </Box>
        </div>
        <div className={classes.detail_items}>
          <Grid container spacing={3}>
            {trade_detail_items.map((item) => (
              <DetailCell item={item} key={item.label} />
            ))}
          </Grid>
        </div>
        <Divider />
        <div>
          <div className={classes.tradeSubSection}>
            <Typography component="subtitle">
              <Trans id="TradeDetail.coins">Coins:</Trans>
            </Typography>
            {Object.keys(presented.offer_dict).map((name) => (
              <OfferRow
                key={name}
                name={name}
                trade={presented}
                amount={presented.offer_dict[name]}
               />
            ))}
          </div>
        </div>
        <div className={classes.card}>
          <Box display="flex">
            <Box flexGrow={1} />
            <Box>
              <Button
                onClick={secure_cancel}
                className={classes.accept}
                variant="contained"
                color="primary"
                style={visible}
              >
                <Trans id="TradeDetail.cancelAndSpend">Cancel and Spend</Trans>
              </Button>
            </Box>
            <Box>
              <Button
                onClick={cancel}
                className={classes.accept}
                variant="contained"
                color="primary"
                style={visible}
              >
                <Trans id="TradeDetail.cancel">Cancel</Trans>
              </Button>
            </Box>
          </Box>
        </div>
      </div>
    </Paper>
  );
};

export const PendingTrades = () => {
  const classes = useStyles();
  const trades = useSelector((state) => state.trade_state.pending_trades);
  return (
    <Paper className={classes.paper}>
      <div className={classes.pending_trades}>
        <Typography component="h6" variant="h6">
          <Trans id="PendingTrades.title">Offers Created</Trans>
        </Typography>
        <TradeTable trades={trades} />
      </div>
    </Paper>
  );
};

export const TradingHistory = () => {
  const classes = useStyles();
  const trades = useSelector((state) => state.trade_state.trade_history);
  return (
    <Paper className={classes.paper}>
      <div className={classes.pending_trades}>
        <Typography component="h6" variant="h6">
          <Trans id="TradingHistory.title">Trading History</Trans>
        </Typography>
        <TradeTable trades={trades} />
      </div>
    </Paper>
  );
};

export const TradingOverview = () => {
  const classes = useStyles();
  const showing_trade = useSelector((state) => state.trade_state.showing_trade);
  const dispatch = useDispatch();

  dispatch(get_all_trades());

  if (showing_trade === true) {
    return (
      <div className={classes.root}>
        <main className={classes.content}>
          <TradeDetail />
        </main>
      </div>
    );
  }
  return (
    <div className={classes.root}>
      <main className={classes.content}>
        <PendingTrades />
        <TradingHistory />
      </main>
    </div>
  );
};
