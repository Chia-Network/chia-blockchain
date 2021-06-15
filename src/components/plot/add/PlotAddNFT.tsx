import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { Button, CardStep, Select, Flex, Loading } from '@chia/core';
import { Box, Grid, FormControl, InputLabel, MenuItem, Typography } from '@material-ui/core';
import usePlotNFTs from '../../../hooks/usePlotNFTs';
import PlotNFTName from '../../plotNFT/PlotNFTName';
import PlotNFTSelectPool from '../../plotNFT/select/PlotNFTSelectPool';

export default function PlotAddNFT() {
  const { nfts, loading } = usePlotNFTs();
  const [showCreatePlotNFT, setShowCreatePlotNFT] = useState<boolean>(false);

  function handleJoinPool() {
    setShowCreatePlotNFT(true);
  }

  function handleCancelPlotNFT() {
    setShowCreatePlotNFT(false);
  }

  if (showCreatePlotNFT) {
    return (
      <PlotNFTSelectPool 
        step={5} 
        onCancel={handleCancelPlotNFT}
        title={<Trans>Create a Plot NFT</Trans>}
        description={(
          <Trans>
            Join a pool and get consistent XCH farming rewards. 
            The average returns are the same, but it is much less volatile.
          </Trans>
        )}
      />
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

      {!loading && !!nfts && !!nfts.length && (
        <>
          <Typography variant="subtitle1">
            <Trans>
              Select your Plot NFT from the dropdown or create a new one.
            </Trans>
          </Typography>

          <Grid spacing={2} direction="column" container>
            <Grid xs={12} md={8} lg={6} item>
              <FormControl
                variant="filled"
                fullWidth
              >
                <InputLabel required>
                  <Trans>Select your Plot NFT</Trans>
                </InputLabel>
                <Select name="p2_singleton_puzzle_hash">
                  <MenuItem value={''}>
                    <em><Trans>None</Trans></em>
                  </MenuItem>
                  {nfts.map((nft) => {
                    const {
                      pool_state: {
                        p2_singleton_puzzle_hash,
                      },
                    } = nft;
              
                    return (
                      <MenuItem value={p2_singleton_puzzle_hash} key={p2_singleton_puzzle_hash}>
                        <PlotNFTName nft={nft} />
                      </MenuItem>
                    );
                  })}
                </Select>
              </FormControl>
            </Grid>

            <Grid xs={12} md={8} lg={6} item>
              <Button
                onClick={handleJoinPool}
                variant="filled"
              >
                <Trans>+ Add New Plot NFT</Trans>
              </Button>
            </Grid>
          </Grid>
        </>
      )}

      {!loading && nfts && !nfts.length && (
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
            >
              <Trans>Join a Pool</Trans>
            </Button>
          </Box>
        </>
      )}
    </CardStep>
  );
}
