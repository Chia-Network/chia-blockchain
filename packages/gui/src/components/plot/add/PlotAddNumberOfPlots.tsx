import React from 'react';
import { Trans, t } from '@lingui/macro';
import {
  AdvancedOptions,
  CardStep,
  TextField,
  RadioGroup,
  Flex,
  Checkbox,
  TooltipIcon,
} from '@chia/core';
import {
  Grid,
  FormControl,
  InputAdornment,
  Typography,
  FormControlLabel,
  Radio,
} from '@mui/material';
import { useFormContext } from 'react-hook-form';
import Plotter from '../../../types/Plotter';

type Props = {
  step: number;
  plotter: Plotter;
};

export default function PlotAddNumberOfPlots(props: Props) {
  const { step, plotter } = props;
  const { watch } = useFormContext();
  const parallel = watch('parallel');

  return (
    <CardStep step={step} title={<Trans>Choose Number of Plots</Trans>}>
      <Grid spacing={2} direction="column" container>
        <Grid xs={12} md={8} lg={6} item>
          <FormControl variant="filled" fullWidth>
            <TextField
              required
              name="plotCount"
              type="number"
              variant="filled"
              placeholder=""
              label={<Trans>Plot Count</Trans>}
              InputProps={{
                inputProps: { min: 1 },
              }}
            />
          </FormControl>
        </Grid>

        {plotter.options.canPlotInParallel && (
          <Grid xs={12} md={8} lg={6} item>
            <Typography>
              <Trans>Does your machine support parallel plotting?</Trans>
            </Typography>
            <Typography color="textSecondary">
              <Trans>
                Plotting in parallel can save time. Otherwise, add plot(s) to the
                queue.
              </Trans>
            </Typography>

            <FormControl variant="filled" fullWidth>
              <RadioGroup name="parallel" boolean>
                <Flex gap={2} flexWrap="wrap">
                  <FormControlLabel
                    value={false}
                    control={<Radio />}
                    label={<Trans>Add Plot to Queue</Trans>}
                  />
                  <FormControlLabel
                    control={<Radio />}
                    label={<Trans>Plot in Parallel</Trans>}
                    value
                  />
                </Flex>
              </RadioGroup>
            </FormControl>
          </Grid>
        )}

        {parallel && (
          <Grid xs={12} md={8} lg={6} item>
            <FormControl variant="filled">
              <Typography variant="subtitle1">
                <Trans>Want to have a delay before the next plot starts?</Trans>
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
                      <Trans>Minutes</Trans>
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
          {plotter.options.canSetBufferSize && (
            <Grid xs={12} sm={6} item>
              <FormControl fullWidth>
                <TextField
                  name="maxRam"
                  type="number"
                  variant="filled"
                  label={<Trans>RAM max usage</Trans>}
                  helperText={<Trans>More memory slightly increases speed</Trans>}
                  InputProps={{
                    inputProps: { min: 0 },
                    endAdornment: (
                      <InputAdornment position="end">MiB</InputAdornment>
                    ),
                  }}
                />
              </FormControl>
            </Grid>
          )}
          <Grid xs={12} sm={6} item>
            <FormControl fullWidth>
              <TextField
                name="numThreads"
                type="number"
                variant="filled"
                placeholder="2"
                label={<Trans>Number of threads</Trans>}
                helperText={plotter.defaults.plotterName === "bladebit" && (
                  <Trans>Specify a value of 0 to use all available threads</Trans>
                )}
                InputProps={{
                  inputProps: { min: 0 },
                }}
              />
            </FormControl>
          </Grid>
          {plotter.options.haveMadmaxThreadMultiplier && (
            <Grid xs={12} sm={6} item>
              <FormControl fullWidth>
                <TextField
                  name="madmaxThreadMultiplier"
                  type="number"
                  variant="filled"
                  placeholder=""
                  label={<Trans>Thread Multiplier for Phase 2</Trans>}
                  helperText={<Trans>A value of {plotter.defaults.madmaxThreadMultiplier} is recommended</Trans>}
                  InputProps={{
                    inputProps: { min: 0 },
                  }}
                />
              </FormControl>
            </Grid>
          )}
          {plotter.options.haveNumBuckets && (
            <Grid xs={12} sm={6} item>
              <FormControl variant="filled" fullWidth>
                <TextField
                  name="numBuckets"
                  type="number"
                  variant="filled"
                  placeholder=""
                  label={<Trans>Number of buckets</Trans>}
                  helperText={<Trans>{plotter.defaults.numBuckets} buckets is recommended</Trans>}
                  InputProps={{
                    inputProps: { min: 0 },
                  }}
                />
              </FormControl>
            </Grid>
          )}
          {plotter.options.haveMadmaxNumBucketsPhase3 && (
            <Grid xs={12} sm={6} item>
            <FormControl variant="filled" fullWidth>
              <TextField
                name="madmaxNumBucketsPhase3"
                type="number"
                variant="filled"
                placeholder=""
                label={<Trans>Number of buckets for phase 3 &amp; 4</Trans>}
                helperText={<Trans>{plotter.defaults.madmaxNumBucketsPhase3} buckets is recommended</Trans>}
                InputProps={{
                  inputProps: { min: 0 },
                }}
              />
            </FormControl>
          </Grid>
          )}
          <Grid xs={12} sm={6} item>
            <FormControl variant="filled" fullWidth>
              <TextField
                name="queue"
                type="text"
                variant="filled"
                placeholder="default"
                label={<Trans>Queue Name</Trans>}
              />
            </FormControl>
          </Grid>
          {plotter.options.canDisableBitfieldPlotting && (
            <Grid xs={12} item>
              <FormControl variant="filled" fullWidth>
                <FormControlLabel
                  control={<Checkbox name="disableBitfieldPlotting" />}
                  label={
                    <>
                      <Trans>Disable bitfield plotting</Trans>{' '}
                      <TooltipIcon>
                        <Trans>
                          Plotting with bitfield enabled has about 30% less
                          overall writes and is now almost always faster. You may
                          see reduced memory requirements with bitfield plotting
                          disabled. If your CPU design is from before 2010 you may
                          have to disable bitfield plotting.
                        </Trans>
                      </TooltipIcon>
                    </>
                  }
                />
              </FormControl>
            </Grid>
          )}
          {plotter.options.haveMadmaxTempToggle && (
            <Grid xs={12} item>
              <FormControl variant="filled" fullWidth>
                <FormControlLabel
                  control={<Checkbox name="madmaxTempToggle" />}
                  label={
                    <>
                      <Trans>Alternate tmpdir/tmpdir2</Trans>{' '}
                    </>
                  }
                />
              </FormControl>
            </Grid>
          )}
          {plotter.options.haveBladebitWarmStart && (
            <Grid xs={12} item>
              <FormControl variant="filled" fullWidth>
                <FormControlLabel
                  control={<Checkbox name="bladebitWarmStart" />}
                  label={
                    <>
                      <Trans>Warm start</Trans>{' '}
                    </>
                  }
                />
              </FormControl>
            </Grid>
          )}
          {plotter.options.haveBladebitDisableNUMA && (
            <Grid xs={12} item>
              <FormControl variant="filled" fullWidth>
                <FormControlLabel
                  control={<Checkbox name="bladebitDisableNUMA" />}
                  label={
                    <>
                      <Trans>Disable NUMA</Trans>{' '}
                    </>
                  }
                />
              </FormControl>
            </Grid>
          )}
          <Grid xs={12} item>
            <FormControl variant="filled" fullWidth>
              <FormControlLabel
                control={<Checkbox name="excludeFinalDir" />}
                label={
                  <>
                    <Trans>Exclude final directory</Trans>{' '}
                    <TooltipIcon>
                      <Trans>
                        Skips adding a final directory to harvester for farming
                      </Trans>
                    </TooltipIcon>
                  </>
                }
              />
            </FormControl>
          </Grid>
          <Grid xs={12} item>
            <FormControl variant="filled" fullWidth>
              <TextField
                name="farmerPublicKey"
                type="text"
                variant="filled"
                placeholder="Hex farmer public key"
                label={<Trans>Farmer Public Key</Trans>}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} item>
            <FormControl variant="filled" fullWidth>
              <TextField
                name="poolPublicKey"
                type="text"
                variant="filled"
                placeholder="Hex public key of pool"
                label={<Trans>Pool Public Key</Trans>}
              />
            </FormControl>
          </Grid>
          <Grid xs={12} item>
            <FormControl variant="filled" fullWidth>
              <TextField
                name="plotNFTContractAddr"
                type="text"
                variant="filled"
                placeholder={t`Plot NFT Plot Target Address`}
                label={<Trans>Plot NFT Pool Contract Address</Trans>}
              />
            </FormControl>
          </Grid>
        </Grid>
      </AdvancedOptions>
    </CardStep>
  );
}
