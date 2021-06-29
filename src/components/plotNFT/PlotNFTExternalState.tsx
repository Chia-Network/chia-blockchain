import React from 'react';
import { Trans } from '@lingui/macro';
import { Typography } from '@material-ui/core';
import type PlotNFTExternal from '../../types/PlotNFTExternal';

type Props = {
  nft: PlotNFTExternal;
};

export default function PlotNFTExternalState(props: Props) {
  const { 
    nft: {
      pool_state: {
        pool_config: {
          pool_url,
        },
      },
    },
  } = props;

  const isSelfPooling = !pool_url;

  return (
    <Typography variant="body1">
      {isSelfPooling && (
        <Trans>Self Pooling</Trans>
      )}
      {!isSelfPooling && (
        <Trans>Pooling</Trans>
      )}
    </Typography>
  );
}
