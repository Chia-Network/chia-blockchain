import React from 'react';
import { Trans } from '@lingui/macro';
import { Indicator } from '@chia/core';
import type Plot from '../../types/Plot';
import useFarmerStatus from '../../hooks/useFarmerStatus';
import FarmerStatus from '../../constants/FarmerStatus';
import StateColor from '../../constants/StateColor';

const Color = {
  [FarmerStatus.FARMING]: StateColor.SUCCESS,
  [FarmerStatus.SYNCHING]: StateColor.WARNING,
  [FarmerStatus.ERROR]: StateColor.ERROR,
};

type Props = {
  plot?: Plot,
};

export default function PlotStatus(props: Props) {
  const { plot } = props;
  const farmerStatus = useFarmerStatus();

  if (!plot) {
    return null;
  }

  return (
    <Indicator color={Color[farmerStatus]}>
      {farmerStatus === FarmerStatus.FARMING && (
        <Trans id="PlotStatus.farming">
          Farming
        </Trans>
      )}
      {farmerStatus === FarmerStatus.SYNCHING && (
        <Trans id="PlotStatus.synching">
          Syncing
        </Trans>
      )}
      {farmerStatus === FarmerStatus.ERROR && (
        <Trans id="PlotStatus.error">
          Error
        </Trans>
      )}
    </Indicator>
  );
}
