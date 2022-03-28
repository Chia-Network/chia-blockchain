import React from 'react';
import { Trans } from '@lingui/macro';
import { Typography } from '@mui/material';
import type PlotNFTExternal from '../../types/PlotNFTExternal';

type Props = {
  nft: PlotNFTExternal;
};

export default function PlotNFTExternalState(props: Props) {
  const {
    nft: {
      poolState: {
        poolConfig: { poolUrl },
      },
    },
  } = props;

  const isSelfPooling = !poolUrl;

  return (
    <Typography variant="body1">
      {isSelfPooling && <Trans>Self Pooling</Trans>}
      {!isSelfPooling && <Trans>Pooling</Trans>}
    </Typography>
  );
}
