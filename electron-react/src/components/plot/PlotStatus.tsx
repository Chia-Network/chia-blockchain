import React from 'react';
import { Trans } from '@lingui/macro';
import { Flex } from '@chia/core';
import styled from 'styled-components';
import type Plot from '../../types/Plot';
import useFarmerStatus from '../../hooks/useFarmerStatus';
import FarmerStatus from '../../constants/FarmerStatus';
import StateColor from '../../constants/StateColor';

const StyledIndicator = styled.div`
  display: inline-block;
  height: 10px;
  width: 75px;
  background-color: ${({ color }) => color};
`;

const Color = {
  [FarmerStatus.FARMING]: StateColor.SUCCESS,
  [FarmerStatus.SYNCHING]: StateColor.WARNING,
  [FarmerStatus.ERROR]: StateColor.ERROR,
};

type Props = {
  plot: Plot,
};

export default function PlotStatus(props: Props) {
  const farmerStatus = useFarmerStatus();

  return (
    <Flex flexDirection="column" gap={1}>
      <StyledIndicator color={Color[farmerStatus]} />

      <Flex>
      {farmerStatus === FarmerStatus.FARMING && (
        <Trans id="PlotStatus.farming">
          Farming
        </Trans>
      )}
      {farmerStatus === FarmerStatus.SYNCHING && (
        <Trans id="PlotStatus.farming">
          Synching
        </Trans>
      )}
      {farmerStatus === FarmerStatus.ERROR && (
        <Trans id="PlotStatus.farming">
          Error
        </Trans>
      )}
      </Flex>
    </Flex>
  );
}
