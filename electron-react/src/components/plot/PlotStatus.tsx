import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Indicator, StateColor, TooltipIcon } from '@chia/core';
import type Plot from '../../types/Plot';
import FarmerStatus from '../../constants/FarmerStatus';

const Color = {
  [FarmerStatus.FARMING]: StateColor.SUCCESS,
  [FarmerStatus.SYNCHING]: StateColor.WARNING,
  [FarmerStatus.NOT_AVAILABLE]: StateColor.WARNING,
  [FarmerStatus.NOT_CONNECTED]: StateColor.ERROR,
  [FarmerStatus.NOT_RUNNING]: StateColor.ERROR,
};

const Title = {
  [FarmerStatus.FARMING]: <Trans id="PlotStatus.farming">Farming</Trans>,
  [FarmerStatus.SYNCHING]: <Trans id="PlotStatus.synching">Syncing</Trans>,
  [FarmerStatus.NOT_AVAILABLE]: <Trans id="PlotStatus.notAvailable">Not Available</Trans>,
  [FarmerStatus.NOT_CONNECTED]: <Trans id="PlotStatus.error">Error</Trans>,
  [FarmerStatus.NOT_RUNNING]: <Trans id="PlotStatus.error">Error</Trans>,
};

const Description = {
  [FarmerStatus.FARMING]: null,
  [FarmerStatus.SYNCHING]: (
    <Trans id="PlotStatus.notAvailableDescription">
      Wait for synchronization
    </Trans>
  ),
  [FarmerStatus.NOT_AVAILABLE]: (
    <Trans id="PlotStatus.notAvailableDescription">
      Wait for synchronization
    </Trans>
  ),
  [FarmerStatus.NOT_CONNECTED]: <Trans id="PlotStatus.farmerIsNotConnected">Farmer is not connected</Trans>,
  [FarmerStatus.NOT_RUNNING]: <Trans id="PlotStatus.farmerIsNotRunning">Farmer is not running</Trans>,
};

type Props = {
  plot?: Plot,
};

export default function PlotStatus(props: Props) {
  const { plot } = props;
  const farmerStatus = FarmerStatus.NOT_AVAILABLE// useFarmerStatus();
  const color = Color[farmerStatus];
  const title = Title[farmerStatus];
  const description = Description[farmerStatus];

  if (!plot) {
    return null;
  }

  return (
    <Indicator color={color}>
      <Flex alignItems="center" gap={1}>
        <span>{title}</span>
        {description && (
          <TooltipIcon>
            {description}
          </TooltipIcon>
        )}
      </Flex>
    </Indicator>
  );
}
