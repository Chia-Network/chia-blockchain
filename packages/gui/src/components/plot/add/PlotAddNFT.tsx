import React, { useState, forwardRef } from 'react';
import { Trans } from '@lingui/macro';
import { Button, CardStep, Select, Flex, Loading } from '@chia/core';
import {
  Box,
  Grid,
  FormControl,
  InputLabel,
  MenuItem,
  Typography,
} from '@mui/material';
import { useFormContext } from 'react-hook-form';
import usePlotNFTs from '../../../hooks/usePlotNFTs';
import PlotNFTName from '../../plotNFT/PlotNFTName';
import PlotNFTSelectPool from '../../plotNFT/select/PlotNFTSelectPool';
import Plotter from '../../../types/Plotter';

type Props = {
  step: number;
  plotter: Plotter;
};

const PlotAddNFT = forwardRef((props: Props, ref) => {
  const { step } = props;
  const { nfts, external, loading } = usePlotNFTs();
  const [showCreatePlotNFT, setShowCreatePlotNFT] = useState<boolean>(false);
  const { setValue } = useFormContext();

  const hasNFTs = !!nfts?.length || !!external?.length;

  function handleJoinPool() {
    setShowCreatePlotNFT(true);
    setValue('createNFT', true);
  }

  function handleCancelPlotNFT() {
    setShowCreatePlotNFT(false);
    setValue('createNFT', false);
  }

  if (showCreatePlotNFT) {
    return (
      <PlotNFTSelectPool
        step={step}
        onCancel={handleCancelPlotNFT}
        ref={ref}
        title={<Trans>Create a Plot NFT</Trans>}
        description={
          <Trans>
            Join a pool and get consistent XCH farming rewards. The average
            returns are the same, but it is much less volatile.
          </Trans>
        }
      />
    );
  }

  return (
    <CardStep
      step={step}
      title={
        <Flex gap={1} alignItems="baseline">
          <Box>
            <Trans>Join a Pool</Trans>
          </Box>
          <Typography variant="body1" color="textSecondary">
            <Trans>(Optional)</Trans>
          </Typography>
        </Flex>
      }
    >
      {loading && <Loading center />}

      {!loading && hasNFTs && (
        <>
          <Typography variant="subtitle1">
            <Trans>
              Select your Plot NFT from the dropdown or create a new one.
            </Trans>
          </Typography>

          <Grid spacing={2} direction="column" container>
            <Grid xs={12} md={8} lg={6} item>
              <FormControl variant="filled" fullWidth>
                <InputLabel required>
                  <Trans>Select your Plot NFT</Trans>
                </InputLabel>
                <Select name="p2SingletonPuzzleHash">
                  <MenuItem value="">
                    <em>
                      <Trans>None</Trans>
                    </em>
                  </MenuItem>
                  {nfts?.map((nft) => {
                    const {
                      poolState: { p2SingletonPuzzleHash },
                    } = nft;

                    return (
                      <MenuItem
                        value={p2SingletonPuzzleHash}
                        key={p2SingletonPuzzleHash}
                      >
                        <PlotNFTName nft={nft} />
                      </MenuItem>
                    );
                  })}
                  {external?.map((nft) => {
                    const {
                      poolState: { p2SingletonPuzzleHash },
                    } = nft;

                    return (
                      <MenuItem
                        value={p2SingletonPuzzleHash}
                        key={p2SingletonPuzzleHash}
                      >
                        <PlotNFTName nft={nft} />
                      </MenuItem>
                    );
                  })}
                </Select>
              </FormControl>
            </Grid>

            <Grid xs={12} md={8} lg={6} item>
              <Button onClick={handleJoinPool} variant="outlined">
                <Trans>+ Add New Plot NFT</Trans>
              </Button>
            </Grid>
          </Grid>
        </>
      )}

      {!loading && !hasNFTs && (
        <>
          <Typography variant="subtitle1">
            <Trans>
              Join a pool and get more consistent XCH farming rewards. Create a
              plot NFT and assign your new plots to a group.
            </Trans>
          </Typography>

          <Box>
            <Button onClick={handleJoinPool} variant="outlined" >
              <Trans>Join a Pool</Trans>
            </Button>
          </Box>
        </>
      )}
    </CardStep>
  );
});

export default PlotAddNFT;
