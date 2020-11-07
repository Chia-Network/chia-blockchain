import React from 'react';
import { Trans } from '@lingui/macro';
import { AdvancedOptions, CardStep, Select, TextField } from '@chia/core';
import { Grid, Link, FormControl, Typography, InputLabel, MenuItem, InputAdornment, FormHelperText } from '@material-ui/core';

const plotCountOptions: number[] = [];

for (let i = 1; i < 30; i++) {
  plotCountOptions.push(i);
}

export default function PlotAddNumberOfPlots() {
  return (
    <CardStep
      step="2"
      title={(
        <Trans id="PlotAddNumberOfPlots.title">Choose Number of Plots</Trans>
      )}
    >
      <Grid container>
        <Grid xs={12} sm={10} md={8} lg={6} item>
          <FormControl
            variant="filled"
            fullWidth
          >
            <InputLabel required>
              <Trans id="PlotAddNumberOfPlots.plotCount">Plot Count</Trans>
            </InputLabel>
            <Select name="plotCount">
              {plotCountOptions.map((count) => (
                <MenuItem value={count} key={count}>
                  {count}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Grid>
      </Grid>

      <AdvancedOptions>
        <Grid spacing={1} container>
          <Grid xs={12} sm={6} item>
            <FormControl
              fullWidth
            >
              <TextField
                name="maxRam"
                type="number"
                variant="filled"
                label={<Trans id="PlotAddNumberOfPlots.ramMaxUsage">RAM max usage</Trans>}
                helperText={(
                  <Trans id="CreatePlot.ramMaxUsageDescription">
                    More memory slightly increases speed
                  </Trans>
                )}
                InputProps={{
                  endAdornment: <InputAdornment position="end">MiB</InputAdornment>,
                }}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} sm={6} item>
            <FormControl
              fullWidth
            >
              <TextField
                name="numThreads"
                type="number"
                variant="filled"
                placeholder="2"
                label={(
                  <Trans id="CreatePlot.numberOfThreads">
                    Number of threads
                  </Trans>
                )}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} sm={6} item>
            <FormControl
              variant="filled"
              fullWidth
            >
              <TextField
                name="numBuckets"
                type="number"
                variant="filled"
                placeholder=""
                label={(
                  <Trans id="CreatePlot.numberOfBuckets">
                    Number of buckets
                  </Trans>
                )}
                helperText={(
                  <Trans id="CreatePlot.numberOfBucketsDescription">
                    0 automatically chooses bucket count
                  </Trans>
                )}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} sm={6} item>
            <FormControl
              variant="filled"
              fullWidth
            >
              <TextField
                name="stripeSize"
                type="number"
                variant="filled"
                placeholder="65536"
                label={<Trans id="CreatePlot.stripeSize">Stripe Size</Trans>}
              />
            </FormControl>
          </Grid>
        </Grid>
      </AdvancedOptions>
    </CardStep>
  );
}
