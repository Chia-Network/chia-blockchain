import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, State, StateTypography, TooltipIcon } from '@hddcoin/core';
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
        current: { state },
        target,
      },
    },
  } = props;

  if (!target && state === PlotNFTStateEnum.LEAVING_POOL) {
    return (
      <Flex alignItems="center" gap={1} inline>
        <StateTypography variant="body1" state={State.ERROR}>
          <Trans>Invalid state</Trans>
        </StateTypography>
        <TooltipIcon>
          <Trans>
            The pool switching operation was cancelled, please try again by
            changing pool, or self pooling
          </Trans>
        </TooltipIcon>
      </Flex>
    );
  }

  const isPending = !!target && target.state !== state;
  if (isPending) {
    return (
      <Flex alignItems="center" gap={1} inline>
        <StateTypography variant="body1" state={State.WARNING}>
          <Trans>Pending</Trans>
        </StateTypography>
        <TooltipIcon>
          <Trans>
            PlotNFT is transitioning to (target state). This can take a while.
            Please do not close the application until this is finalized.
          </Trans>
        </TooltipIcon>
      </Flex>
    );
  }

  return (
    <Typography variant="body1">
      {state === PlotNFTStateEnum.SELF_POOLING && <Trans>Self Pooling</Trans>}
      {state === PlotNFTStateEnum.LEAVING_POOL && <Trans>Leaving Pool</Trans>}
      {state === PlotNFTStateEnum.FARMING_TO_POOL && <Trans>Pooling</Trans>}
    </Typography>
  );
}
