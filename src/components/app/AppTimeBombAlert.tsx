import React from 'react';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Alert } from '@material-ui/lab';
import { RootState } from '../../modules/rootReducer';

const CRITICAL_HEIGHT = 4608 * 42; // 6 weeks

export default function AppTimeBomb() {
  const peakHeight = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.peak?.height ?? 0,
  );

  const isVisible = peakHeight >= CRITICAL_HEIGHT;
  if (isVisible) {
    return (
      <Alert severity="warning">
        <Trans>This version of Chia is no longer compatible with the blockchain and can not safely farm.</Trans>
      </Alert>
    );
  }

  return null;
}
