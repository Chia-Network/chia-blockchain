import React from 'react';
import { Grid } from '@material-ui/core';
import FullNodeCardStatus from './FullNodeCardStatus';
import FullNodeCardConnectionStatus from './FullNodeCardConnectionStatus';
import FullNodeCardNetworkName from './FullNodeCardNetworkName';
import FullNodeCardPeakHeight from './FullNodeCardPeakHeight';
import FullNodeCardPeakTime from './FullNodeCardPeakTime';
import FullNodeCardDifficulty from './FullNodeCardDifficulty';
import FullNodeCardVDFSubSlotIterations from './FullNodeCardVDFSubSlotIterations';
import FullNodeCardTotalIterations from './FullNodeCardTotalIterations';
import FullNodeEstimatedNetworkSpace from './FullNodeEstimatedNetworkSpace';

type Props = {
  wallet_id: number;
};

export default function FullNodeCards(props: Props) {
  return (
    <div>
      <Grid spacing={3} alignItems="stretch" container>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardStatus />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardConnectionStatus />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardNetworkName />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardPeakHeight />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardPeakTime />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardDifficulty />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardVDFSubSlotIterations />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FullNodeCardTotalIterations />
        </Grid>
        <Grid xs={12} md={4} item>
          <FullNodeEstimatedNetworkSpace />
        </Grid>
      </Grid>
    </div>
  );
}
