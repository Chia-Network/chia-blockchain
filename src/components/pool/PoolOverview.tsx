import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useToggle } from 'react-use';
import { Flex, UnitFormat, More, State, Table } from '@chia/core';
import { useHistory } from 'react-router';
import { 
  ViewList as ViewListIcon,
  ViewModule as ViewModuleIcon,
  Payment as PaymentIcon,
  Power as PowerIcon,
} from '@material-ui/icons';
import { Box, Button, ListItemIcon, MenuItem, IconButton, Grid, Tooltip, Typography } from '@material-ui/core';
import { sumBy } from 'lodash';
import PlotNFTCard from '../plotNFT/PlotNFTCard';
import PlotNFTName from '../plotNFT/PlotNFTName';
import PlotNFTState from '../plotNFT/PlotNFTState';
import PoolWalletStatus from '../wallet/WalletStatus';
import PlotNFTAbsorbRewards from '../plotNFT/PlotNFTAbsorbRewards';
import PoolJoin from './PoolJoin';
import PoolHero from './PoolHero';
import type PlotNFT from '../../types/PlotNFT';
import usePlotNFTs from '../../hooks/usePlotNFTs';
import PlotNFTStateEnum from '../../constants/PlotNFTState';
import PlotNFTUnconfirmedCard from '../plotNFT/PlotNFTUnconfirmedCard';
import useUnconfirmedPlotNFTs from '../../hooks/useUnconfirmedPlotNFTs';
import { mojo_to_chia } from '../../util/chia';

const groupsCols = [
  {
    field: (nft: PlotNFT) => <PlotNFTName nft={nft} />,
    title: <Trans>Plot NFT</Trans>,
  },
  {
    field: () => <PoolWalletStatus />,
    title: <Trans>Wallet Status</Trans>,
  },
  {
    field: (nft: PlotNFT) => <PlotNFTState nft={nft} />,
    title: <Trans>Status</Trans>,
  },
  {
    field: (nft: PlotNFT) => {
      const { 
        pool_wallet_status: {
          current: {
            state,
          },
        },
      } = nft;

      if (state === PlotNFTStateEnum.SELF_POOLING) {
        return (
          <UnitFormat value={mojo_to_chia(BigInt(nft.wallet_balance.confirmed_wallet_balance ?? 0))} />
        );
      }
      
      return null;
    },
    title: <Trans>Rewards</Trans>,
  },
  {
    title: <Trans>Actions</Trans>,
    field(nft: PlotNFT) {
      const isSelfPooling = nft.pool_wallet_status.current.state === PlotNFTStateEnum.SELF_POOLING;

      return (
        <More>
          {({ onClose }) => (
            <Box>
              {isSelfPooling && (
                <PlotNFTAbsorbRewards nft={nft}>
                  {(absorbRewards) => (
                    <MenuItem onClick={() => { onClose(); absorbRewards(); }}>
                      <ListItemIcon>
                        <PaymentIcon fontSize="small" />
                      </ListItemIcon>
                      <Typography variant="inherit" noWrap>
                        <Trans>Claim Rewards</Trans>
                      </Typography>
                    </MenuItem>
                  )}
                </PlotNFTAbsorbRewards>
              )}

              <PoolJoin nft={nft}>
                {({ join, disabled }) => (
                  <MenuItem onClick={() => { onClose(); join(); }} disabled={disabled}>
                    <ListItemIcon>
                      <PowerIcon fontSize="small" />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      {isSelfPooling 
                        ? <Trans>Join Pool</Trans>
                        : <Trans>Change Pool</Trans>}
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
  const history = useHistory();
  const [showTable, toggleShowTable] = useToggle(false);
  const { nfts, loading } = usePlotNFTs();
  const { unconfirmed } = useUnconfirmedPlotNFTs();

  const hasNFTs = (!!nfts && !!nfts.length) || unconfirmed.length;

  const totalWinning = useMemo<number>(
    () => nfts && nfts.length
      ? sumBy<PlotNFT>(nfts, (item) => item.wallet_balance.confirmed_wallet_balance ?? 0)
      : 0, 
    [nfts],
  );

  function handleAddPool() {
    history.push('/dashboard/pool/add');
  }

  function handleToggleView() {
    toggleShowTable();
  }

  if (loading) {
    return null;
  }

  if (!hasNFTs) {
    return (
      <PoolHero />
    );
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
        <Flex justifyContent="flex-end" alignItems="center" gap={2}>
          <Tooltip title={showTable ? <Trans>Grid view</Trans> : <Trans>List view</Trans>}>
            <IconButton size="small" onClick={handleToggleView}>
              {showTable ? <ViewModuleIcon /> : <ViewListIcon />}
            </IconButton>
          </Tooltip>
          <Flex gap={1} >
            <Typography variant="body1" color="textSecondary">
              <Trans>
                Total Self Pooling Rewards
              </Trans>
            </Typography>
            <UnitFormat value={mojo_to_chia(BigInt(totalWinning))} state={State.SUCCESS} />
          </Flex>
        </Flex>
        {showTable ? (
          <Table
            uniqueField="p2_singleton_puzzle_hash"
            rows={nfts} 
            cols={groupsCols} 
          />
        ) : (
          <Grid spacing={3} alignItems="stretch" container>
            {unconfirmed.map((unconfirmedPlotNFT) => (
              <Grid key={unconfirmedPlotNFT.transactionId} xs={12} md={6} item>
                <PlotNFTUnconfirmedCard unconfirmedPlotNFT={unconfirmedPlotNFT} />
              </Grid>
            ))}
            {nfts.map((nft) => (
              <Grid key={nft.pool_state.p2_singleton_puzzle_hash} xs={12} md={6} item>
                <PlotNFTCard nft={nft} />
              </Grid>
            ))}
          </Grid>
        )}
      </Flex>
    </Flex>
  );
}
