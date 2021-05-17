import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { Flex, State, UnitFormat } from '@chia/core';
import {
  Button,
  Grid,
  Card,
  CardContent,
  Typography,
} from '@material-ui/core';
import type PoolGroup from '../../types/PoolGroup';
import type { RootState } from '../../modules/rootReducer';
import PoolName from './PoolName';
import PoolStatus from './PoolStatus';
import PoolWalletStatus from './PoolWalletStatus';
import usePoolClaimRewards from '../../hooks/usePoolClaimRewards';
import usePoolJoin from '../../hooks/usePoolJoin';

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
  pool: PoolGroup;
};

export default function PoolCard(props: Props) {
  const { 
    pool,
    pool: {
      self,
      state,
      balance,
    },
  } = props;

  const [claimRewards] = usePoolClaimRewards(pool);
  const [joinPool] = usePoolJoin(pool);

  const isWalletSyncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );

  const isPooling = state === 'FREE' || state === 'POOLING';
  const isSelfPooling = isPooling && self;

  async function handleClaimRewards() {
    return claimRewards();
  }

  async function handleJoinPool() {
    return joinPool();
  }

  return (
    <StyledCard>
      <StyledCardContent>
        <Flex flexDirection="column" gap={4} flexGrow={1}>
          <PoolName pool={pool} variant="h6" />

          <Flex flexDirection="column" flexGrow={1}>
            <Grid container spacing={1}>
              <Grid container xs={4} lg={3} item>
                <Typography variant='body1' color="textSecondary"> 
                  <Trans>Pool Winnings</Trans>
                </Typography>
              </Grid>
              <Grid container xs={8} lg={9} item>
                <UnitFormat value={balance} state={State.SUCCESS} />
              </Grid>
              <Grid container xs={4} lg={3} item>
                <Typography variant='body1' color="textSecondary"> 
                  <Trans>Wallet Status</Trans>
                </Typography>
              </Grid>
              <Grid container xs={8} lg={9} item>
                <PoolWalletStatus />
              </Grid>
              <Grid container xs={4} lg={3} item>
                <Typography variant="body1" color="textSecondary"> 
                  <Trans>Pool Status</Trans>
                </Typography>
              </Grid>
              <Grid container xs={8} lg={9} item>
                <PoolStatus pool={pool} />
              </Grid>
            </Grid>
          </Flex>

          {!isWalletSyncing && (
            <Grid container spacing={1}>
              <Grid container xs={6} item>
                <Button
                  variant="contained"
                  onClick={handleClaimRewards}
                  fullWidth
                >
                  <Flex flexDirection="column" gap={0}>
                    <Typography variant="body1">
                      <Trans>Claim Rewards</Trans>
                    </Typography>
                  </Flex>
                </Button>
              </Grid>
              <Grid container xs={6} item>
                <Button
                  variant="contained"
                  onClick={handleJoinPool}
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
      {isWalletSyncing && (
        <StyledSyncingFooter>
          <Flex alignItems="center">
            <Typography variant="body2">
              <Trans>
                You can still create plots for this pool group, but you can not make changes until sync is complete.
              </Trans>
            </Typography>
          </Flex>
        </StyledSyncingFooter>
      )}
    </StyledCard>
  );
}
