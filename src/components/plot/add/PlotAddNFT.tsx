import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Button, AdvancedOptions, CardStep, Select, Flex, Loading, Checkbox, TooltipIcon } from '@chia/core';
import { Box, Grid, FormControl, InputLabel, MenuItem, Typography, FormControlLabel } from '@material-ui/core';
import usePlotNFT from '../../../hooks/usePlotNFT';
import GroupName from '../../group/GroupName';
import GroupAdd from '../../group/add/GroupAdd';

export default function PlotAddNFT() {
  const { groups, loading } = usePlotNFT();
  const [showCreatePlotNFT, setShowCreatePlotNFT] = useState<boolean>(false);

  function handleJoinPool() {
    setShowCreatePlotNFT(true);
  }

  function handleCancelPlotNFT() {
    setShowCreatePlotNFT(false);
  }

  if (showCreatePlotNFT) {
    return (
      <GroupAdd step={5} onCancel={handleCancelPlotNFT} />
    );
  }

  return (
    <CardStep
      step="5"
      title={(
        <Flex gap={1} alignItems="baseline">
          <Box>
            <Trans>Join a Pool</Trans>
          </Box>
          <Typography variant="body1" color="textSecondary">
            <Trans>(Optional)</Trans>
          </Typography>
        </Flex>
      )}
    >
      {loading && (
        <Flex alignItems="center">
          <Loading />
        </Flex>
      )}

      {!loading && !!groups && !!groups.length && (
        <>
          <Typography variant="subtitle1">
            <Trans>
              Select your Plot NFT from the dropdown.
            </Trans>
          </Typography>

          <Grid spacing={2} direction="column" container>
            <Grid xs={12} md={8} lg={6} item>
              <FormControl
                variant="filled"
                fullWidth
              >
                <InputLabel required>
                  <Trans>Select your Plot NFT or create a new one</Trans>
                </InputLabel>
                <Select name="nft">
                  {groups.map((group) => (
                    <MenuItem value={group.pool_config.launcher_id} key={group.pool_config.launcher_id}>
                      <GroupName group={group} />
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid xs={12} md={8} lg={6} item>
              <Button
                onClick={handleJoinPool}
                variant="contained"
              >
                <Trans>Create New</Trans>
              </Button>
            </Grid>
          </Grid>
        </>
      )}

      {!loading && groups && !groups.length && (
        <>
          <Typography variant="subtitle1">
            <Trans>
              Join a pool and get more consistent XCH farming rewards. Create a plot NFT and assign your new plots to a group.
            </Trans>
          </Typography>

          <Box>
            <Button
              onClick={handleJoinPool}
              variant="contained"
              color="primary"
            >
              <Trans>Join a Pool</Trans>
            </Button>
          </Box>
        </>
      )}
    </CardStep>
  );
}
