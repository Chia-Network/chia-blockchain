import { useDispatch, useSelector } from 'react-redux';
import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import {
  Paper,
  Button,
  CircularProgress,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';
import {
  resetTrades,
  offerParsingName,
  parsingStarted,
  parsingStatePending,
} from '../../modules/trade';

import {
  accept_trade_action,
  parse_trade_action,
} from '../../modules/trade_messages';
import { Card } from '@chia/core';
import TradesTable from './TradesTable';

/* global BigInt */

const useStyles = makeStyles((theme) => ({
  root: {
    display: 'flex',
    paddingLeft: '0px',
  },
  toolbar: {
    paddingRight: 24, // keep right padding when drawer closed
  },
  toolbarIcon: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    padding: '0 8px',
    ...theme.mixins.toolbar,
  },
  appBar: {
    zIndex: theme.zIndex.drawer + 1,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
  },
  paper: {
    margin: theme.spacing(3),
    padding: theme.spacing(0),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
  },
  balancePaper: {
    margin: theme.spacing(3),
  },
  copyButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(0),
    width: 50,
    height: 56,
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(4),
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1),
  },
  tradeSubSection: {
    color: '#cccccc',
    borderRadius: 4,
    backgroundColor: '#555555',
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    marginTop: theme.spacing(1),
    padding: 15,
    overflowWrap: 'break-word',
  },
  formControl: {
    widht: '100%',
  },
  input: {
    height: 56,
    width: '100%',
  },
  send: {
    marginLeft: theme.spacing(2),
    paddingLeft: '0px',
    height: 56,
    width: 150,
  },
  card: {
    paddingTop: theme.spacing(10),
    height: 200,
  },
  saveButton: {
    width: '100%',
    marginTop: theme.spacing(4),
    marginRight: theme.spacing(1),
    marginBottom: theme.spacing(2),
    height: 56,
  },
  cancelButton: {
    width: '100%',
    marginTop: theme.spacing(4),
    marginLeft: theme.spacing(1),
    marginBottom: theme.spacing(2),
    height: 56,
  },
  drag: {
    backgroundColor: '#888888',
    height: 300,
    width: '100%',
  },
  dragText: {
    margin: 0,
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
  },
  circle: {
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
}));

export const DropView = () => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const handleDragEnter = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();

    const offer_file_path = e.dataTransfer.files[0].path;
    const offer_name = offer_file_path.replace(/^.*[/\\]/, '');

    dispatch(offerParsingName(offer_name, offer_file_path));
    dispatch(parse_trade_action(offer_file_path));
    dispatch(parsingStarted());
  };
  const parsing_state = useSelector((state) => state.trade_state.parsing_state);
  const parsing = parsing_state === parsingStatePending;

  const progressStyle = parsing
    ? { visibility: 'visible' }
    : { visibility: 'hidden' };
  const textStyle = !parsing
    ? { visibility: 'visible' }
    : { visibility: 'hidden' };

  return (
    <Card
      title={<Trans id="OfferDropView.selectOffer">Select Offer</Trans>}
    >
      <div
        onDrop={(e) => handleDrop(e)}
        onDragOver={(e) => handleDragOver(e)}
        onDragEnter={(e) => handleDragEnter(e)}
        onDragLeave={(e) => handleDragLeave(e)}
      >
        <Paper className={classes.drag} style={{ position: 'relative' }}>
          <div className={classes.dragText} style={textStyle}>
            <Trans id="OfferDropView.dragAndDropOfferFile">
              Drag and drop offer file
            </Trans>
          </div>
          <div className={classes.circle} style={progressStyle}>
            <CircularProgress color="secondary" />
          </div>
        </Paper>
      </div>
    </Card>
  );
};

export const OfferView = () => {
  const offer = useSelector((state) => state.trade_state.parsed_offer);
  const dispatch = useDispatch();
  const file_path = useSelector((state) => state.trade_state.parsed_offer_path);

  function handleAccept() {
    dispatch(accept_trade_action(file_path));
  }

  function handleDecline() {
    dispatch(resetTrades());
  }

  const trades = useMemo(() => {
    return Object.keys(offer).map((name) => ({
      amount: offer[name],
      name,
    }));
  }, offer);

  return (
    <Card
      title={<Trans id="OfferView.title2">Offer</Trans>}
      actions={(
        <>
          <Button
            onClick={handleDecline}
            variant="contained"
          >
            <Trans id="OfferView.cancel">Cancel</Trans>
          </Button>
          <Button
            onClick={handleAccept}
            variant="contained"
            color="primary"
          >
            <Trans id="OfferView.accept">Accept</Trans>
          </Button>
        </>
      )}
    >
      <TradesTable rows={trades} />
    </Card>
  );
};

export const OfferSwitch = () => {
  const showOffer = useSelector((state) => state.trade_state.show_offer);

  if (showOffer) {
    return <OfferView />;
  }
  return <DropView />;
};
