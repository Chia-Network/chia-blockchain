import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router';
import { Flex, State, UnitFormat, CardKeyValue, Tooltip, More, Loading } from '@chia/core';
import {
  Box,
  Button,
  Grid,
  Card,
  CardContent,
  Typography,
  MenuItem,
  ListItemIcon,
} from '@material-ui/core';
import type PlotNFT from '../../types/PlotNFT';
import type { RootState } from '../../modules/rootReducer';
import PlotNFTName from './PlotNFTName';
import PlotNFTStatus from './PlotNFTState';
import WalletStatus from '../wallet/WalletStatus';
import useAbsorbRewards from '../../hooks/useAbsorbRewards';
import useJoinPool from '../../hooks/useJoinPool';
import PlotIcon from '../icons/Plot';
import usePlotNFTDetails from '../../hooks/usePlotNFTDetails';
import PlotNFTState from '../../constants/PlotNFTState';

const StyledCard = styled(Card)`
  display: flex;
  flex-direction: column;
  height: 100%;
`;

const StyledCardContent = styled(CardContent)`
  display: flex;
  flex-direction: column;
  flex-grow: 1;
`;

const StyledSyncingFooter = styled(CardContent)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#515151' : '#F6F6F6'};
  padding: 2rem 3rem;
  text-align: center;
  borer-top: 1px solid #D8D6D6;
`;

type Props = {
  nft: PlotNFT;
};

export default function PlotNFTCard(props: Props) {
  const { 
    nft,
    nft: {
      pool_state: {
        p2_singleton_puzzle_hash,
        pool_config: {
          pool_url,
          launcher_id,
        },
      },
      wallet_balance: {
        confirmed_wallet_balance: balance = 0,
      },
    },
  } = props;

  const history = useHistory();
  const absorbRewards = useAbsorbRewards(nft);
  const joinPool = useJoinPool(nft);
  const { canEdit, isSynced, plots, state } = usePlotNFTDetails(nft);

  const isSelfPooling = state === PlotNFTState.SELF_POOLING;

  async function handleClaimRewards() {
    if (canEdit) {
      return absorbRewards();
    }
  }

  async function handleJoinPool() {
    if (canEdit) {
      history.push(`/dashboard/pool/${p2_singleton_puzzle_hash}/change-pool`);
    }
  }

  function handleAddPlot() {
    history.push({
      pathname: '/dashboard/plot/add',
      state: {
        p2_singleton_puzzle_hash,
      },
    });
  }

  const rows = [isSelfPooling && {
    key: 'rewards',
    label: <Trans>Rewards</Trans>,
    value: <UnitFormat value={balance} state={State.SUCCESS} />,
  }, {
    key: 'status',
    label: <Trans>Status</Trans>,
    value: <PlotNFTStatus nft={nft} />,
  }, {
    key: 'wallet_status',
    label: <Trans>Wallet Status</Trans>,
    value: <WalletStatus />,
  }, {
    key: 'current_difficulty',
    label: <Trans>Current Difficulty</Trans>,
    value: nft.pool_state.current_difficulty,
  }, {
    key: 'current_points_balance',
    label: <Trans>Current Points Balance</Trans>,
    value: nft.pool_state.current_points_balance,
  }, {
    key: 'points_found_since_start',
    label: <Trans>Points Found Since Start</Trans>,
    value: nft.pool_state.points_found_since_start,
  }, {
    key: 'plots_count',
    label: <Trans>Number of Plots</Trans>,
    value: plots
      ? plots.length
      : <Loading size="small" />,
  }].filter(row => !!row && row.value !== undefined);

  return (
    <StyledCard>
      <StyledCardContent>
        <Flex flexDirection="column" gap={4} flexGrow={1}>
          <Flex flexDirection="column" gap={1}>
            <Flex gap={1}>
              <Box flexGrow={1}>
                <PlotNFTName nft={nft} variant="h6" />
              </Box>
              <More>
                {({ onClose }) => (
                  <Box>
                    <MenuItem onClick={() => { onClose(); handleAddPlot(); }}>
                      <ListItemIcon>
                        <PlotIcon />
                      </ListItemIcon>
                      <Typography variant="inherit" noWrap>
                        <Trans>Add a Plot</Trans>
                      </Typography>
                    </MenuItem>
                  </Box>
                )}
              </More>
            </Flex>
          </Flex>

          <Flex flexDirection="column" flexGrow={1}>
            <CardKeyValue rows={rows} hideDivider />
          </Flex>

          <Flex flexDirection="column" gap={1}>
            <Typography variant="body1" color="textSecondary" noWrap>
              <Trans>Launcher Id</Trans>
            </Typography>
            <Tooltip title={launcher_id} copyToClipboard>
              <Typography variant="body2" noWrap>
                {launcher_id}
              </Typography>
            </Tooltip>
          </Flex> 


          {isSynced && (
            <Grid container spacing={1}>
              {isSelfPooling && (
                <Grid container xs={6} item>
                  <Button
                    variant="contained"
                    onClick={handleClaimRewards}
                    disabled={!canEdit}
                    fullWidth
                  >
                    <Flex flexDirection="column" gap={0}>
                      <Typography variant="body1">
                        <Trans>Claim Rewards</Trans>
                      </Typography>
                    </Flex>
                  </Button>
                </Grid>
              )}

              <Grid container xs={isSelfPooling ? 6 : 12} item>
                <Button
                  variant="contained"
                  onClick={handleJoinPool}
                  disabled={!canEdit}
                  color="primary"
                  fullWidth
                >
                  <Flex flexDirection="column" gap={1}>
                    <Typography variant="body1">
                      {isSelfPooling 
                        ? <Trans>Join Pool</Trans>
                        : <Trans>Change Pool</Trans>
                      }
                    </Typography>
                  </Flex>
                </Button>
              </Grid>
            </Grid>
          )}
        </Flex>
      </StyledCardContent>
      {!isSynced && (
        <StyledSyncingFooter>
          <Flex alignItems="center">
            <Typography variant="body2">
              <Trans>
                You can still create plots for this plot NFT, but you can not make changes until sync is complete.
              </Trans>
            </Typography>
          </Flex>
        </StyledSyncingFooter>
      )}
    </StyledCard>
  );
}
