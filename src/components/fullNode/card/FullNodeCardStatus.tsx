import React from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { FormatLargeNumber } from '@chia/core';
import styled from 'styled-components';
import FarmCard from '../../farm/card/FarmCard';
import type { RootState } from '../../../modules/rootReducer';

const StyledWarning = styled.span`
  color: #f7ca3e;
`;

function getData(state) {
  if (state?.sync && state?.sync?.sync_mode) {
    const progress = state?.sync?.sync_progress_height;
    const tip = state?.sync?.sync_tip_height;
    return {
      value: (
        <StyledWarning>
          <Trans>
            Syncing <FormatLargeNumber value={progress} />/
            <FormatLargeNumber value={tip} />
          </Trans>
        </StyledWarning>
      ),
      color: 'orange',
      tooltip: (
        <Trans>
          The node is syncing, which means it is downloading blocks from other
          nodes, to reach the latest block in the chain
        </Trans>
      ),
    };
  } else if (!state?.sync?.synced) {
    return {
      value: <Trans>Not Synced</Trans>,
      color: 'error',
      tooltip: <Trans>The node is not synced</Trans>,
    };
  } else {
    return {
      value: <Trans>Synced</Trans>,
      color: 'primary',
      tooltip: (
        <Trans>This node is fully caught up and validating the network</Trans>
      ),
    };
  }
}

export default function FullNodeCardStatus() {
  const state = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state,
  );

  const { value, tooltip, color } = getData(state);

  return (
    <FarmCard
      valueColor={color}
      title={<Trans>Status</Trans>}
      tooltip={tooltip}
      value={value}
    />
  );
}
