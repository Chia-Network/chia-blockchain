import React from 'react';
import { Trans } from '@lingui/macro';
import moment from 'moment';
import { OfferTradeRecord } from '@chia/api';
import { Flex } from '@chia/core';
import path from 'path';

type OfferViewerTitleProps = {
  offerFilePath?: string;
  tradeRecord?: OfferTradeRecord;
};

export default function OfferViewerTitle(
  props: OfferViewerTitleProps,
): React.ReactElement {
  const { offerFilePath, tradeRecord } = props;
  const offerFileName = offerFilePath
    ? path.basename(offerFilePath)
    : undefined;

  return (
    <Flex flexDirection="row" style={{ wordBreak: 'break-all' }}>
      {offerFileName ? (
        <Trans>Viewing offer: {offerFileName}</Trans>
      ) : tradeRecord ? (
        <Trans>
          Viewing offer created at{' '}
          {moment(tradeRecord.createdAtTime * 1000).format('LLL')}
        </Trans>
      ) : (
        <Trans>Viewing offer</Trans>
      )}
    </Flex>
  );
}
