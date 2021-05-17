import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { Flex, CardStep, Select, RadioGroup } from '@chia/core';
import { Grid, FormControl, FormControlLabel, Typography, InputLabel, MenuItem, Radio } from '@material-ui/core';
import type PoolGroup from '../../../types/PoolGroup';

export default function PoolAddCreate() {
  const pools = useSelector<PoolGroup[] | undefined>((state: RootState) => state.pool_group.pools);

  const poolsOptions = useMemo(() => {
    if (!pools) {
      return [];
    }

    return pools
      .filter(pool => !!pool.poolUrl)
      .map(pool => ({
        value: pool.poolUrl,
        label: pool.poolUrl,
      }));
  }, [pools]);

  return (
    <CardStep
      step="1"
      title={<Trans>Want to Join a Pool? Create a Group</Trans>}
    >
      <Typography variant="subtitle1">
        <Trans>
          Join a pool and get consistent XCH farming rewards. 
          The average returns are the same, but it is much less volatile. 
          Assign plots to a group. When pools are released, 
          you can easily switch pools without having to re-plot.
        </Trans>
      </Typography>

      <Grid container>
        <Grid xs={12} item>
          <FormControl
            variant="filled"
            fullWidth
          >
            <RadioGroup name="self" boolean>
              <Flex gap={1} flexDirection="column">
                <FormControlLabel
                  control={<Radio />}
                  label={<Trans>Self pool. When you win a block you will earn XCH rewards.</Trans>}
                  value
                />
                <Flex gap={2} flexWrap="nowrap">
                  <FormControlLabel
                    value={false}
                    control={<Radio />}
                    label={<Trans>Connect to pool</Trans>}
                  />
                  <Flex flexBasis={0} flexGrow={1}>
                  <FormControl
                    variant="filled"
                    fullWidth
                  >
                    <InputLabel>
                      <Trans>Pool URL</Trans>
                    </InputLabel>
                    <Select name="poolUrl">
                      {poolsOptions.map((option) => (
                        <MenuItem value={option.value} key={option.value}>
                          {option.label}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  </Flex>
                </Flex>

              </Flex>
            </RadioGroup>
          </FormControl>
        </Grid>
      </Grid>
    </CardStep>
  );
}
