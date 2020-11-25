import React from 'react';
import plotSizes from '../../../constants/plotSizes';
import type PlotQueueItem from '../../../types/PlotQueueItem';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueSize(props: Props) {
  const { queueItem: { config: { plotSize } } } = props;
  const item = plotSizes.find((item) => item.value === plotSize);
  if (!item) {
    return null;
  }

  return (
    <>
      {`K-${plotSize}, ${item.label}`}
    </>
  );
}
