import React from 'react';
import styled from 'styled-components';
import { Trans } from '@lingui/macro';
import { useSelector } from 'react-redux';
import { Flex, State, UnitFormat } from '@chia/core';
import {
  Box,
  Button,
  Grid,
  Card,
  CardContent,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableRow,
} from '@material-ui/core';
import type Group from '../../types/Group';
import type { RootState } from '../../modules/rootReducer';
import GroupName from './GroupName';
import GroupStatus from './GroupStatus';
import WalletStatus from '../wallet/WalletStatus';
import usePoolClaimRewards from '../../hooks/useGroupClaimRewards';
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
  group: Group;
};

const LEFT_SIZE_XS = 6;
const RIGHT_SIZE_XS= 6;

const LEFT_SIZE_LG = 5;
const RIGHT_SIZE_LG= 7;

export default function GroupCard(props: Props) {
  const { 
    group,
    group: {
      state,
      balance = 0,
      pool_config: {
        pool_url,
      },
    },
  } = props;

  const [claimRewards] = usePoolClaimRewards(group);
  const [joinPool] = usePoolJoin(group);

  const isWalletSyncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );

  const isPooling = state === 'FREE' || state === 'POOLING';
  const isSelfPooling = !pool_url;

  async function handleClaimRewards() {
    return claimRewards();
  }

  async function handleJoinPool() {
    return joinPool();
  }

  const rows = [{
    label: <Trans>Current Difficulty</Trans>,
    value: group.current_difficulty,
  }, {
    label: <Trans>Current Points Balance</Trans>,
    value: group.current_points_balance,
  }, {
    label: <Trans>Points Found Since Start</Trans>,
    value: group.points_found_since_start,
  }].filter(row => row.value !== undefined);

  return (
    <StyledCard>
      <StyledCardContent>
        <Flex flexDirection="column" gap={4} flexGrow={1}>
          <Box component="div" textOverflow="ellipsis">
            <GroupName group={group} variant="h6" />
          </Box>

          <Flex flexDirection="column" flexGrow={1}>
            <Table size="small" aria-label="a dense table">
              <TableBody>
                <TableRow>
                  <TableCell>
                    <Typography variant='body1' color="textSecondary"> 
                      <Trans>Pool Winnings</Trans>
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body1"> 
                      <UnitFormat value={balance} state={State.SUCCESS} />
                    </Typography>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>
                    <Typography variant='body1' color="textSecondary"> 
                      <Trans>Wallet Status</Trans>
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body1"> 
                      <WalletStatus />
                    </Typography>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>
                    <Typography variant='body1' color="textSecondary"> 
                      <Trans>Pool Status</Trans>
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Typography variant="body1"> 
                      <GroupStatus group={group} />
                    </Typography>
                  </TableCell>
                </TableRow>
                {rows.map((row) => (
                  <TableRow key={row.label}>
                    <TableCell>
                      <Typography variant="body1" color="textSecondary"> 
                        {row.label}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body1"> 
                        {row.value}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Flex>

          {/** 
          <Flex flexDirection="column" flexGrow={1}>
            <Grid container spacing={1}>
              <Grid container xs={LEFT_SIZE_XS} lg={LEFT_SIZE_LG} item>
                <Typography variant='body1' color="textSecondary"> 
                  <Trans>Pool Winnings</Trans>
                </Typography>
              </Grid>
              <Grid container xs={RIGHT_SIZE_XS} lg={RIGHT_SIZE_LG} item>
                <UnitFormat value={balance} state={State.SUCCESS} />
              </Grid>

              <Grid container xs={LEFT_SIZE_XS} lg={LEFT_SIZE_LG} item>
                <Typography variant='body1' color="textSecondary"> 
                  <Trans>Wallet Status</Trans>
                </Typography>
              </Grid>
              <Grid container xs={RIGHT_SIZE_XS} lg={RIGHT_SIZE_LG} item>
                <WalletStatus />
              </Grid>

              <Grid container xs={LEFT_SIZE_XS} lg={LEFT_SIZE_LG} item>
                <Typography variant="body1" color="textSecondary"> 
                  <Trans>Pool Status</Trans>
                </Typography>
              </Grid>
              <Grid container xs={RIGHT_SIZE_XS} lg={RIGHT_SIZE_LG} item>
                <GroupStatus group={group} />
              </Grid>

              <Grid container xs={LEFT_SIZE_XS} lg={LEFT_SIZE_LG} item>
                <Typography variant="body1" color="textSecondary"> 
                  <Trans>Current Difficulty</Trans>
                </Typography>
              </Grid>
              <Grid container xs={RIGHT_SIZE_XS} lg={RIGHT_SIZE_LG} item>
                {group.current_difficulty}
              </Grid>

              <Grid container xs={LEFT_SIZE_XS} lg={LEFT_SIZE_LG} item>
                <Typography variant="body1" color="textSecondary"> 
                  <Trans>Current Points Balance</Trans>
                </Typography>
              </Grid>
              <Grid container xs={RIGHT_SIZE_XS} lg={RIGHT_SIZE_LG} item>
                {group.current_points_balance}
              </Grid>

              <Grid container xs={LEFT_SIZE_XS} lg={LEFT_SIZE_LG} item>
                <Typography variant="body1" color="textSecondary"> 
                  <Trans>Points Found Since Start</Trans>
                </Typography>
              </Grid>
              <Grid container xs={RIGHT_SIZE_XS} lg={RIGHT_SIZE_LG} item>
                {group.points_found_since_start}
              </Grid>
            </Grid>
          </Flex>
          */}

          {!isWalletSyncing && (
            <Grid container spacing={1}>
              {isSelfPooling && (
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
              )}

              <Grid container xs={isSelfPooling ? 6 : 12} item>
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
