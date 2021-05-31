import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { useWatch, useFormContext } from "react-hook-form";
import { Autocomplete, Flex, CardStep, RadioGroup } from '@chia/core';
import { Grid, FormControl, FormControlLabel, Typography, Radio } from '@material-ui/core';
import type Group from '../../../types/Group';
import PoolDetails from '../../pool/PoolDetails';

export default function GroupAddCreate() {
  const groups = useSelector<Group[] | undefined>((state: RootState) => state.group.groups);
  const { control, setValue } = useFormContext();
  const self = useWatch<boolean>({
    control,
    name: 'self',
  });

  const poolUrl = useWatch<string>({
    control,
    name: 'poolUrl',
  });

  console.log('current pool url', poolUrl);

  const groupsOptions = useMemo(() => {
    if (!groups) {
      return [];
    }

    return groups
      .filter((group) => !!group.poolUrl)
      .map((group) => group.poolUrl);
  }, [groups]);

  function handleDisableSelfPooling() {
    if (self) {
      setValue('self', false);
    }
  }

  return (
    <CardStep
      step="1"
      title={<Trans>Want to Join a Pool? Create a Plot NFT</Trans>}
    >
      <Typography variant="subtitle1">
        <Trans>
          Join a pool and get consistent XCH farming rewards. 
          The average returns are the same, but it is much less volatile. 
          Assign plots to a plot NFT. When pools are released, 
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
                <Flex gap={2} alignItems="start">
                  <FormControlLabel
                    value={false}
                    control={<Radio />}
                    label={<Trans>Connect to pool</Trans>}
                  />
                  <Flex flexBasis={0} flexGrow={1} flexDirection="column" gap={1}>
                    <FormControl
                      variant="filled"
                      fullWidth
                    >
                      <Autocomplete
                        name="poolUrl"
                        label="Pool URL"
                        variant="outlined"
                        options={groupsOptions}
                        onClick={handleDisableSelfPooling}
                        onChange={handleDisableSelfPooling}
                        forcePopupIcon
                        fullWidth 
                        freeSolo 
                      />
                    </FormControl>

                    {!self && poolUrl && (
                      <PoolDetails poolUrl={poolUrl} />
                    )}
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
