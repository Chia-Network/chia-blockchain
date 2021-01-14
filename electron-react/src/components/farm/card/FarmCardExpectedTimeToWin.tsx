import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { useSelector } from 'react-redux';
import { FiberManualRecord as FiberManualRecordIcon } from '@material-ui/icons';
import moment from 'moment';
import { Flex } from '@chia/core';
import type { RootState } from '../../../modules/rootReducer';
import FarmCard from './FarmCard';
import type Plot from '../../../types/Plot';
import StateColor from '../../../constants/StateColor';
import FullNodeState from '../../../constants/FullNodeState';
import useFullNodeState from '../../../hooks/useFullNodeState';

const StyledFiberManualRecordIcon = styled(FiberManualRecordIcon)`
  font-size: 1rem;
`;

const StyledFlexContainer = styled(({ color: Color, ...rest }) => <Flex {...rest} />)`
  color: ${({ color }) => color};
`;

const MINUTES_PER_BLOCK = (24 * 60) / 4608; // 0.3125

export default function FarmCardExpectedTimeToWin() {
  const fullNodeState = useFullNodeState();

  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots,
  );
  const totalNetworkSpace = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.space ?? 0,
  );

  const farmerSpace = useMemo(() => {
    if (!plots) {
      return 0;
    }

    return plots.map((p: Plot) => p.file_size).reduce((a, b) => a + b, 0);
  }, [plots]);

  const proportion = totalNetworkSpace 
    ? farmerSpace / totalNetworkSpace 
    : 0;

  const minutes = proportion 
    ? MINUTES_PER_BLOCK / proportion 
    : 0;

  const expectedTimeToWin = moment.duration({ minutes }).humanize();

  if (fullNodeState !== FullNodeState.SYNCED) {
    return (
      <FarmCard
        title={
          <Trans id="FarmCardExpectedTimeToWin.title">Expected Time to Win</Trans>
        }
        value={(
          <StyledFlexContainer color={StateColor.WARNING} alignItems="center" gap={1}>
            <Trans id="FarmCardExpectedTimeToWin.synching">Syncing</Trans>
          </StyledFlexContainer>
        )}
      />
    );

  }

  return (
    <FarmCard
      title={
        <Trans id="FarmCardExpectedTimeToWin.title">Expected Time to Win</Trans>
      }
      value={`${expectedTimeToWin}`}
      tooltip={
        <Trans id="FarmCardExpectedTimeToWin.tooltip">
          You have {(proportion * 100).toFixed(4)}% of the space on the network,
          so farming a block will take {expectedTimeToWin} in expectation.
        </Trans>
      }
    />
  );
}
