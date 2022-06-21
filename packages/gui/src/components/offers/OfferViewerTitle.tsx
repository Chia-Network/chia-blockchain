import React from 'react';
import { Trans } from '@lingui/macro';
import moment from 'moment';
import { OfferTradeRecord } from '@chia/api';
import { Flex, useColorModeValue } from '@chia/core';
import { Typography } from '@mui/material';
import path from 'path';
import styled from 'styled-components';

const StyledHeaderBox = styled.div`
  padding-top: ${({ theme }) => `${theme.spacing(1)}`};
  padding-bottom: ${({ theme }) => `${theme.spacing(1)}`};
  padding-left: ${({ theme }) => `${theme.spacing(2)}`};
  padding-right: ${({ theme }) => `${theme.spacing(2)}`};
  border-radius: 4px;
  border: ${({ theme }) => `1px solid ${useColorModeValue(theme, 'border')}`};
  background-color: ${({ theme }) => theme.palette.background.paper};
`;

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

  function OfferTitleValue() {
    if (offerFileName) {
      return offerFileName;
    } else if (tradeRecord) {
      return (
        <Trans>
          created {moment(tradeRecord.createdAtTime * 1000).format('LLL')}
        </Trans>
      );
    }

    return null;
  }

  const offerTitleValue = OfferTitleValue();

  return (
    <Flex flexDirection="row" style={{ wordBreak: 'break-all' }}>
      <Flex flexDirection="row" gap={2}>
        <Flex flexDirection="row" alignItems="center">
          <Typography variant="inherit">
            <Trans>Viewing offer</Trans>
          </Typography>
        </Flex>
        {offerTitleValue && (
          <Flex flexDirection="row">
            <StyledHeaderBox>
              <Typography variant="body1" color="textSecondary">
                {offerTitleValue}
              </Typography>
            </StyledHeaderBox>
          </Flex>
        )}
      </Flex>
    </Flex>
  );
}
