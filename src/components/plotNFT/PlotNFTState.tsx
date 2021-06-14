import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, State, StateTypography, TooltipIcon } from '@chia/core';
import { Typography } from '@material-ui/core';
import type PlotNFT from '../../types/PlotNFT';
import PlotNFTStateEnum from '../../constants/PlotNFTState';

type Props = {
  nft: PlotNFT;
};

export default function PlotNFTState(props: Props) {
  const { 
    nft: {
      pool_wallet_status: {
        current: {
          state,
        },
        target,
      },
    },
  } = props;

  const isPending = target && target !== state;
  const isSelfPooling = state === PlotNFTStateEnum.SELF_POOLING;

  if (isPending) {
    return (
      <Flex alignItems="center" gap={1}>
        <StateTypography variant='body1' state={State.WARNING}>
          <Trans>Pending</Trans>
        </StateTypography>
        <TooltipIcon>
          <Trans>Unconfirmed transaction</Trans>
        </TooltipIcon>
      </Flex>
    );
  }

  return (
    <Typography variant="body1">
      {isSelfPooling ? (
        <Trans>Self Pooling</Trans>
      ) : (
        <Trans>Pooling</Trans>
      )}
    </Typography>
  );
}
