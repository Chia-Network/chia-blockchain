import React from 'react';
import { Trans } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Button, Flex, UnitFormat, More, Table, mojoToChiaLocaleString, Suspender } from '@chia/core';
import { useNavigate } from 'react-router';
import {
  ViewList as ViewListIcon,
  ViewModule as ViewModuleIcon,
  Payment as PaymentIcon,
  Power as PowerIcon,
} from '@mui/icons-material';
import {
  Box,
  ListItemIcon,
  MenuItem,
  IconButton,
  Grid,
  Tooltip,
  Typography,
} from '@mui/material';
import PlotNFTCard from '../plotNFT/PlotNFTCard';
import PlotExternalNFTCard from '../plotNFT/PlotExternalNFTCard';
import PlotNFTName from '../plotNFT/PlotNFTName';
import PoolAbsorbRewards from './PoolAbsorbRewards';
import PoolJoin from './PoolJoin';
import PoolHero from './PoolHero';
import type PlotNFT from '../../types/PlotNFT';
import usePlotNFTs from '../../hooks/usePlotNFTs';
import PlotNFTStateEnum from '../../constants/PlotNFTState';
import PlotNFTUnconfirmedCard from '../plotNFT/PlotNFTUnconfirmedCard';
import PlotNFTState from '../plotNFT/PlotNFTState';
import useUnconfirmedPlotNFTs from '../../hooks/useUnconfirmedPlotNFTs';
import { WalletStatus } from '@chia/wallets';

const groupsCols = [
  {
    field: (nft: PlotNFT) => <PlotNFTName nft={nft} />,
    title: <Trans>Plot NFT</Trans>,
  },
  {
    field: (nft: PlotNFT) => <PlotNFTState nft={nft} />,
    title: <Trans>Status</Trans>,
  },
  {
    field: (nft: PlotNFT) => {
      const {
        poolWalletStatus: {
          current: { state },
        },
      } = nft;

      if (state === PlotNFTStateEnum.SELF_POOLING) {
        return (
          <UnitFormat
            value={mojoToChiaLocaleString(nft.walletBalance.confirmedWalletBalance ?? 0)}
          />
        );
      }

      return null;
    },
    title: <Trans>Unclaimed Rewards</Trans>,
  },
  {
    title: <Trans>Actions</Trans>,
    field(nft: PlotNFT) {
      const isSelfPooling =
        nft.poolWalletStatus.current.state === PlotNFTStateEnum.SELF_POOLING;

      return (
        <More>
          {({ onClose }) => (
            <Box>
              {isSelfPooling && (
                <PoolAbsorbRewards nft={nft}>
                  {({ absorb, disabled }) => (
                    <MenuItem
                      onClick={() => {
                        onClose();
                        absorb();
                      }}
                      disabled={disabled}
                    >
                      <ListItemIcon>
                        <PaymentIcon fontSize="small" />
                      </ListItemIcon>
                      <Typography variant="inherit" noWrap>
                        <Trans>Claim Rewards</Trans>
                      </Typography>
                    </MenuItem>
                  )}
                </PoolAbsorbRewards>
              )}

              <PoolJoin nft={nft}>
                {({ join, disabled }) => (
                  <MenuItem
                    onClick={() => {
                      onClose();
                      join();
                    }}
                    disabled={disabled}
                  >
                    <ListItemIcon>
                      <PowerIcon fontSize="small" />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      {isSelfPooling ? (
                        <Trans>Join Pool</Trans>
                      ) : (
                        <Trans>Change Pool</Trans>
                      )}
                    </Typography>
                  </MenuItem>
                )}
              </PoolJoin>
            </Box>
          )}
        </More>
      );
    },
  },
];

export default function PoolOverview() {
  const navigate = useNavigate();
  const [showTable, toggleShowTable] = useToggle(false);
  const { nfts, external, loading } = usePlotNFTs();
  const { unconfirmed } = useUnconfirmedPlotNFTs();

  const hasNFTs =
    (!!nfts && !!nfts?.length) || !!external?.length || unconfirmed.length;

  function handleAddPool() {
    navigate('/dashboard/pool/add');
  }

  function handleToggleView() {
    toggleShowTable();
  }

  if (loading) {
    return <Suspender />;
  }

  if (!hasNFTs) {
    return <PoolHero />;
  }

  return (
    <Flex flexDirection="column" gap={1}>
      <Flex gap={1}>
        <Flex flexGrow={1}>
          <Flex flexDirection="column" gap={1}>
            <Typography variant="h5" gutterBottom>
              <Trans>Your Pool Overview</Trans>
            </Typography>
          </Flex>
        </Flex>
        <Flex flexDirection="column" gap={1}>
          <Flex alignItems="center" justifyContent="flex-end" gap={1}>
            <Button variant="outlined" color="primary" onClick={handleAddPool}>
              + Add a Plot NFT
            </Button>
          </Flex>
        </Flex>
      </Flex>
      <Flex flexDirection="column" gap={1}>
        {showTable ? (
          <Table
            uniqueField="poolState.p2SingletonPuzzleHash"
            rows={nfts}
            cols={groupsCols}
          />
        ) : (
          <Grid spacing={3} alignItems="stretch" container>
            {unconfirmed.map((unconfirmedPlotNFT) => (
              <Grid key={unconfirmedPlotNFT.transactionId} xs={12} md={6} item>
                <PlotNFTUnconfirmedCard
                  unconfirmedPlotNFT={unconfirmedPlotNFT}
                />
              </Grid>
            ))}
            {nfts?.map((item) => (
              <Grid
                key={item.poolState.p2SingletonPuzzleHash}
                xs={12}
                md={6}
                item
              >
                <PlotNFTCard nft={item} />
              </Grid>
            ))}
            {external?.map((item) => (
              <Grid
                key={item.poolState.p2SingletonPuzzleHash}
                xs={12}
                md={6}
                item
              >
                <PlotExternalNFTCard nft={item} />
              </Grid>
            ))}
          </Grid>
        )}
      </Flex>
    </Flex>
  );
}
