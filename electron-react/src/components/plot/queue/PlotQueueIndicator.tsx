import React from 'react';
import { Trans } from '@lingui/macro';
import { Indicator } from '@chia/core';
import PlotStatusEnum from '../../../constants/PlotStatus';
import type PlotQueueItem from '../../../types/PlotQueueItem';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueIndicator(props: Props) {
  const { queueItem: { state } } = props;

  return (
    <Indicator color="#979797">
      {state === PlotStatusEnum.RUNNING && (
        <Trans id="PlotQueueIndicator.plotting">
          Plotting
        </Trans>
      )}
      {state === PlotStatusEnum.SUBMITTED && (
        <Trans id="PlotQueueIndicator.queued">
          Queued
        </Trans>
      )}
      {state === PlotStatusEnum.ERROR && (
        <Trans id="PlotQueueIndicator.error">
          Error
        </Trans>
      )}
    </Indicator>
  );
}