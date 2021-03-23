import React from 'react';
import { Trans } from '@lingui/macro';
import { Indicator } from '@chia/core';
import PlotStatusEnum from '../../../constants/PlotStatus';
import type PlotQueueItem from '../../../types/PlotQueueItem';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueIndicator(props: Props) {
  const { queueItem: { state, progress } } = props;

  return (
    <Indicator color="#979797" progress={progress}>
      {state === PlotStatusEnum.RUNNING && (
        <Trans>
          Plotting
        </Trans>
      )}
      {state === PlotStatusEnum.SUBMITTED && (
        <Trans>
          Queued
        </Trans>
      )}
      {state === PlotStatusEnum.ERROR && (
        <Trans>
          Error
        </Trans>
      )}
    </Indicator>
  );
}