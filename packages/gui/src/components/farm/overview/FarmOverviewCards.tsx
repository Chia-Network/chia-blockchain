import React from 'react';
import { Grid } from '@material-ui/core';
import FarmCardStatus from '../card/FarmCardStatus';
import FarmCardTotalChiaFarmed from '../card/FarmCardTotalChiaFarmed';
import FarmCardBlockRewards from '../card/FarmCardBlockRewards';
import FarmCardUserFees from '../card/FarmCardUserFees';
import FarmCardLastHeightFarmed from '../card/FarmCardLastHeightFarmed';
import FarmCardTotalSizeOfPlots from '../card/FarmCardTotalSizeOfPlots';
import FarmCardTotalNetworkSpace from '../card/FarmCardTotalNetworkSpace';
import FarmCardPlotCount from '../card/FarmCardPlotCount';
import FarmCardExpectedTimeToWin from '../card/FarmCardExpectedTimeToWin';

export default function FarmOverviewCards() {
  return (
    <div>
      <Grid spacing={3} alignItems="stretch" container>
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
