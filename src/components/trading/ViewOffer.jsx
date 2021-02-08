import { useDispatch, useSelector } from 'react-redux';
import React, { useMemo } from 'react';
import { Dropzone } from '@chia/core';
import { Trans } from '@lingui/macro';
import { Button } from '@material-ui/core';
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

export const DropView = () => {
  const dispatch = useDispatch();
  const parsing_state = useSelector((state) => state.trade_state.parsing_state);
  const isParsing = parsing_state === parsingStatePending;
 
  function handleDrop(acceptedFiles) {
    const offer_file_path = acceptedFiles[0].path;
    const offer_name = offer_file_path.replace(/^.*[/\\]/, '');

    dispatch(offerParsingName(offer_name, offer_file_path));
    dispatch(parse_trade_action(offer_file_path));
    dispatch(parsingStarted());
  }

  return (
    <Card
      title={<Trans>Select Offer</Trans>}
    >
      <Dropzone onDrop={handleDrop} processing={isParsing}>
        <Trans>
          Drag and drop offer file
        </Trans>
      </Dropzone>
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
      title={<Trans>Offer</Trans>}
      actions={(
        <>
          <Button
            onClick={handleDecline}
            variant="contained"
          >
            <Trans>Cancel</Trans>
          </Button>
          <Button
            onClick={handleAccept}
            variant="contained"
            color="primary"
          >
            <Trans>Accept</Trans>
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
