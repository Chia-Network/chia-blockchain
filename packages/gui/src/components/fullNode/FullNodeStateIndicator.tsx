import React from 'react';
import { Loading, State, StateIndicator } from '@chia/core';
import useFullNodeState from '../../hooks/useFullNodeState';
import FullNodeState from '../../constants/FullNodeState';

export type FullNodeStateIndicatorProps = {
  color?: string;
};

export default function FullNodeStateIndicator(
  props: FullNodeStateIndicatorProps,
) {
  const { color } = props;
  const { state, isLoading } = useFullNodeState();

  if (isLoading) {
    return <Loading size={14} />;
  }

  if (state === FullNodeState.ERROR) {
    return (
      <StateIndicator state={State.ERROR} color={color} indicator hideTitle />
    );
  } else if (state === FullNodeState.SYNCED) {
    return (
      <StateIndicator state={State.SUCCESS} color={color} indicator hideTitle />
    );
  } else if (state === FullNodeState.SYNCHING) {
    return (
      <StateIndicator state={State.WARNING} color={color} indicator hideTitle />
    );
  }

  return null;
}
