import React from 'react';
import { Trans } from '@lingui/macro';
import { AdvancedOptions, CardStep, Select, TextField, RadioGroup, Flex, Checkbox, TooltipIcon } from '@chia/core';
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
                  label={<Trans>Plot in Parallel</Trans>}
                  value
                />
                <FormControlLabel
                  value={false}
                  control={<Radio />}
                  label={<Trans>Add Plot to Queue</Trans>}
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
                    128 buckets is recommended
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
                name="queue"
                type="text"
                variant="filled"
                placeholder="default"
                label={<Trans>Queue Name</Trans>}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} item>
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
                label={(
                  <>
                    <Trans>
                      Disable bitfield plotting
                    </Trans>
                    {' '}
                    <TooltipIcon>
                      <Trans>
                        Plotting with bitfield enabled has about 30% less overall writes and is now almost always faster. You may see reduced memory requirements with bitfield plotting disabled. If your CPU design is from before 2010 you may have to disable bitfield plotting. 
                      </Trans>
                    </TooltipIcon>
                  </>
                )}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} item>
            <FormControl
              variant="filled"
              fullWidth
            >
              <FormControlLabel
                control={(
                  <Checkbox
                    name="excludeFinalDir"
                  />
                )}
                label={(
                  <>
                    <Trans>
                      Exclude final directory
                    </Trans>
                    {' '}
                    <TooltipIcon>
                      <Trans>
                        Skips adding a final directory to harvester for farming
                      </Trans>
                    </TooltipIcon>
                  </>
                )}
              />
            </FormControl>
          </Grid>
        </Grid>
      </AdvancedOptions>
    </CardStep>
  );
}
