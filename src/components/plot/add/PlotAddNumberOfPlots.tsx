import React from 'react';
import { Trans } from '@lingui/macro';
import { AdvancedOptions, CardStep, Select, TextField, RadioGroup, Flex, Checkbox } from '@chia/core';
import { Grid, FormControl, InputLabel, MenuItem, InputAdornment, Typography, FormControlLabel, Radio } from '@material-ui/core';
import { useFormContext } from 'react-hook-form';

const plotCountOptions: number[] = [];

for (let i = 1; i < 30; i += 1) {
  plotCountOptions.push(i);
}

export default function PlotAddNumberOfPlots() {
  const { watch } = useFormContext();
  const parallel = watch('parallel');

  return (
    <CardStep
      step="2"
      title={(
        <Trans>Choose Number of Plots</Trans>
      )}
    >
      <Grid spacing={2} direction="column" container>
        <Grid xs={12} md={8} lg={6} item>
          <FormControl
            variant="filled"
            fullWidth
          >
            <InputLabel required>
              <Trans>Plot Count</Trans>
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

        <Grid xs={12} md={8} lg={6} item>
          <Typography variant="body1">
            <Trans>
              Does your machine support parallel plotting?
            </Trans>
          </Typography>
          <Typography variant="body2">
            <Trans>
              Plotting in parallel can save time. Otherwise, add plot(s) to the queue.
            </Trans>
          </Typography>

          <FormControl
            variant="filled"
            fullWidth
          >
            <RadioGroup name="parallel" boolean>
              <Flex gap={2} flexWrap="wrap">
                <FormControlLabel
                  control={<Radio />}
                  label="Plot in Parallel"
                  value
                />
                <FormControlLabel
                  value={false}
                  control={<Radio />}
                  label="Add Plot to Queue"
                />
              </Flex>
            </RadioGroup>
          </FormControl>
        </Grid>

        {parallel && (
          <Grid xs={12} md={8} lg={6} item>
            <FormControl
              variant="filled"
            >
              <Typography variant="subtitle1">
                <Trans>
                  Want to have a delay before the next plot starts?
                </Trans>
              </Typography>
              <TextField
                name="delay"
                type="number"
                variant="filled"
                label={<Trans>Delay</Trans>}
                InputProps={{
                  inputProps: { min: 0 },
                  endAdornment: (
                    <InputAdornment position="end">
                      <Trans>
                        Minutes
                      </Trans>
                    </InputAdornment>
                  ),
                }}
              />
            </FormControl>
          </Grid>
        )}
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
                label={<Trans>RAM max usage</Trans>}
                helperText={(
                  <Trans>
                    More memory slightly increases speed
                  </Trans>
                )}
                InputProps={{
                  inputProps: { min: 0 },
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
                  <Trans>
                    Number of threads
                  </Trans>
                )}
                InputProps={{
                  inputProps: { min: 0 },
                }}
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
                  <Trans>
                    Number of buckets
                  </Trans>
                )}
                helperText={(
                  <Trans>
                    0 automatically chooses bucket count
                  </Trans>
                )}
                InputProps={{
                  inputProps: { min: 0 },
                }}
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
                label={<Trans>Stripe Size</Trans>}
                InputProps={{
                  inputProps: { min: 0 },
                }}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} sm={6} item>
            <FormControl
              variant="filled"
              fullWidth
            >
              <FormControlLabel
                control={(
                  <Checkbox
                    name="disableBitfieldPlotting"
                  />
                )}
                label="Disable bitfield plotting"
              />
            </FormControl>
          </Grid>
        </Grid>
      </AdvancedOptions>
    </CardStep>
  );
}
