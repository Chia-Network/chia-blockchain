import React from 'react';
import { Box, Typography } from '@material-ui/core';
import { Trans } from '@lingui/macro';
import type PlotNFT from '../../types/PlotNFT';
import usePlotNFTDetails from '../../hooks/usePlotNFTDetails';
import { Flex, TooltipIcon } from '@chia/core';

type Props = {
  nft: PlotNFT;
  variant?: string;
};

export default function PlotNFTName(props: Props) {
  const {
    variant,
    nft,
    nft: {
      pool_state: {
        p2_singleton_puzzle_hash,
      },
    },
  } = props;

  const { humanName } = usePlotNFTDetails(nft)

  return (
    <Flex gap={1} alignItems="center">
      <Typography variant={variant} noWrap>
        {humanName}
      </Typography>
      <TooltipIcon>
        <Flex flexDirection="column">
          <Box>
            <Trans>Atogenerated name from p2_singleton_puzzle_hash</Trans>
          </Box>
          {p2_singleton_puzzle_hash}
        </Flex>
      </TooltipIcon>
    </Flex>

  );
}

PlotNFTName.defaultProps = {
  variant: 'body1',
};
