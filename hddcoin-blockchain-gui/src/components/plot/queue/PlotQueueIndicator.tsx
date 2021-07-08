import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Indicator, StateColor, TooltipIcon } from '@hddcoin/core';
import { Box } from '@material-ui/core';
import PlotStatusEnum from '../../../constants/PlotStatus';
import type PlotQueueItem from '../../../types/PlotQueueItem';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueIndicator(props: Props) {
  const {
    queueItem: { error, state, progress },
  } = props;

  if (error) {
    return (
      <Indicator color={StateColor.ERROR}>
        <Flex alignItems="center" gap={1}>
          <Box>
            <Trans>Error</Trans>
          </Box>
          <TooltipIcon>
            <Box>{error}</Box>
          </TooltipIcon>
        </Flex>
      </Indicator>
    );
  }

  return (
    <Indicator color="#979797" progress={progress}>
      {state === PlotStatusEnum.RUNNING && <Trans>Plotting</Trans>}
      {state === PlotStatusEnum.SUBMITTED && <Trans>Queued</Trans>}
      {state === PlotStatusEnum.REMOVING && <Trans>Removing</Trans>}
    </Indicator>
  );
}
