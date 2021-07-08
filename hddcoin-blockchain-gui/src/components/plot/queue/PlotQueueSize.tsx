import React from 'react';
import plotSizes from '../../../constants/plotSizes';
import type PlotQueueItem from '../../../types/PlotQueueItem';

type Props = {
  queueItem: PlotQueueItem;
};

export default function PlotQueueSize(props: Props) {
  const {
    queueItem: { size },
  } = props;
  const item = plotSizes.find((item) => item.value === size);
  if (!item) {
    return null;
  }

  return <>{`K-${size}, ${item.label}`}</>;
}
