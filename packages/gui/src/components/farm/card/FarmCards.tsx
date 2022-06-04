import React from 'react';
import { Grid } from '@mui/material';
import FarmCardStatus from '../card/FarmCardStatus';
import FarmCardTotalChiaFarmed from './FarmCardTotalChiaFarmed';
import FarmCardBlockRewards from './FarmCardBlockRewards';
import FarmCardUserFees from './FarmCardUserFees';
import FarmCardLastHeightFarmed from './FarmCardLastHeightFarmed';
import FarmCardTotalSizeOfPlots from './FarmCardTotalSizeOfPlots';
import FarmCardTotalNetworkSpace from './FarmCardTotalNetworkSpace';
import FarmCardPlotCount from './FarmCardPlotCount';
import FarmCardExpectedTimeToWin from './FarmCardExpectedTimeToWin';

export default function FarmCards() {
  return (
    <div>
      <Grid spacing={2} alignItems="stretch" container>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardStatus />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardTotalChiaFarmed />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardBlockRewards />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardUserFees />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardLastHeightFarmed />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardPlotCount />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardTotalSizeOfPlots />
        </Grid>
        <Grid xs={12} sm={6} md={4} item>
          <FarmCardTotalNetworkSpace />
        </Grid>
        <Grid xs={12} md={4} item>
          <FarmCardExpectedTimeToWin />
        </Grid>
      </Grid>
    </div>
  );
}
