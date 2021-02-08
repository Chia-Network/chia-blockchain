import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex, Indicator, StateColor, TooltipIcon } from '@chia/core';
import type Plot from '../../types/Plot';
import useFarmerStatus from '../../hooks/useFarmerStatus';
import FarmerStatus from '../../constants/FarmerStatus';

const Color = {
  [FarmerStatus.FARMING]: StateColor.SUCCESS,
  [FarmerStatus.SYNCHING]: StateColor.WARNING,
  [FarmerStatus.NOT_AVAILABLE]: StateColor.WARNING,
  [FarmerStatus.NOT_CONNECTED]: StateColor.ERROR,
  [FarmerStatus.NOT_RUNNING]: StateColor.ERROR,
};

const Title = {
  [FarmerStatus.FARMING]: <Trans>Farming</Trans>,
  [FarmerStatus.SYNCHING]: <Trans>Syncing</Trans>,
  [FarmerStatus.NOT_AVAILABLE]: <Trans>Not Available</Trans>,
  [FarmerStatus.NOT_CONNECTED]: <Trans>Error</Trans>,
  [FarmerStatus.NOT_RUNNING]: <Trans>Error</Trans>,
};

const Description = {
  [FarmerStatus.FARMING]: null,
  [FarmerStatus.SYNCHING]: (
    <Trans>
      Wait for synchronization
    </Trans>
  ),
  [FarmerStatus.NOT_AVAILABLE]: (
    <Trans>
      Wait for synchronization
    </Trans>
  ),
  [FarmerStatus.NOT_CONNECTED]: <Trans>Farmer is not connected</Trans>,
  [FarmerStatus.NOT_RUNNING]: <Trans>Farmer is not running</Trans>,
};

type Props = {
  plot?: Plot,
};

export default function PlotStatus(props: Props) {
  const { plot } = props;
  const farmerStatus = useFarmerStatus();
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
