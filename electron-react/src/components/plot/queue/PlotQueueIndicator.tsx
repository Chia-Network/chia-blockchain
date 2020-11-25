import React from 'react';
import { Trans } from '@lingui/macro';
import { Indicator } from '@chia/core';
import PlotStatusEnum from '../../../constants/PlotStatus';
import type PlotQueueItem from '../../../types/PlotQueueItem';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueIndicator(props: Props) {
  const { queueItem: { status } } = props;

  return (
    <Indicator color="#979797">
      {status === PlotStatusEnum.IN_PROGRESS && (
        <Trans id="PlotQueueIndicator.plotting">
          Plotting
        </Trans>
      )}
      {status === PlotStatusEnum.WAITING && (
        <Trans id="PlotQueueIndicator.queued">
          Queued
        </Trans>
      )}
    </Indicator>
  );
}