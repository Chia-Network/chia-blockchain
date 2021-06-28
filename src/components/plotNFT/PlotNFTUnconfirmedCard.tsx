import React, { useEffect } from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { Flex, Link, Loading } from '@chia/core';
import {
  Box,
  Card,
  CardContent,
  Typography,
} from '@material-ui/core';
import type UnconfirmedPlotNFT from '../../types/UnconfirmedPlotNFT';
import useTransaction from '../../hooks/useTransaction';
import PlotNFTState from '../../constants/PlotNFTState';
import useUnconfirmedPlotNFTs from '../../hooks/useUnconfirmedPlotNFTs';

const StyledCard = styled(Card)`
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 388px;
`;

const StyledCardContent = styled(CardContent)`
  display: flex;
  flex-direction: column;
  flex-grow: 1;
`;

type Props = {
  unconfirmedPlotNFT: UnconfirmedPlotNFT;
};

export default function PlotNFTUnconfirmedCard(props: Props) {
  const { 
    unconfirmedPlotNFT: {
      transactionId,
      state,
      poolUrl,
    },
  } = props;

  const { remove } = useUnconfirmedPlotNFTs();
  const [transaction] = useTransaction(transactionId);

  useEffect(() => {
    if (transaction?.confirmed) {
      remove(transaction.name);
    }
  }, [transaction?.confirmed]);

  return (
    <StyledCard>
      <StyledCardContent>
        <Flex flexDirection="column" gap={4} flexGrow={1}>
          <Box>
            <Typography variant="h6" align="center">
              {state === PlotNFTState.SELF_POOLING
                ? <Trans>Creating Plot NFT for Self Pooling</Trans>
                : <Trans>Creating Plot NFT and Joining the Pool</Trans>}
            </Typography>
            {state === PlotNFTState.FARMING_TO_POOL && (
              <Flex alignItems="center" gap={1} justifyContent="center">
                <Typography variant="body2" color="textSecondary">
                  <Trans>Pool:</Trans>
                </Typography>
                <Link target="_blank" href={poolUrl}>{poolUrl}</Link>
              </Flex>
            )}
          </Box>
          <Flex flexGrow={1} alignItems="center" justifyContent="center" flexDirection="column" gap={2}>
            <Loading />
            <Typography variant="body2" align="center">
              <Trans>Waiting for the transaction to be confirmed</Trans>
            </Typography>
          </Flex>
        </Flex>
      </StyledCardContent>
    </StyledCard>
  );
}
