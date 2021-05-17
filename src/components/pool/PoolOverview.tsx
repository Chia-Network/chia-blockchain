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
import { useSelector } from 'react-redux';
import { Box, Button, ListItemIcon, MenuItem, IconButton, Grid, Tooltip, Typography } from '@material-ui/core';
import type { RootState } from '../../modules/rootReducer';
import { sumBy } from 'lodash';
import type PoolGroup from '../../types/PoolGroup';
import PoolCard from './PoolCard';
import PoolName from './PoolName';
import PoolStatus from './PoolStatus';
import PoolWalletStatus from './PoolWalletStatus';
import PoolClaimRewards from './PoolClaimRewards';
import PoolJoin from './PoolJoin';
import PoolHero from './PoolHero';

const poolsCols = [
  {
    field: (pool: PoolGroup) => <PoolName pool={pool} />,
    title: <Trans>Pool Name: URL</Trans>,
  },
  {
    field: () => <PoolWalletStatus />,
    title: <Trans>Wallet Status</Trans>,
  },
  {
    field: (pool: PoolGroup) => <PoolStatus pool={pool} />,
    title: <Trans>Pool Status</Trans>,
  },
  {
    field: (pool: PoolGroup) => <UnitFormat value={pool.balance} />,
    title: <Trans>Pool Winnings</Trans>,
  },
  {
    title: <Trans>Actions</Trans>,
    field(pool: PoolGroup) {
      return (
        <More>
          {({ onClose }) => (
            <Box>
              <PoolClaimRewards pool={pool}>
                {(claimRewards) => (
                  <MenuItem onClick={() => { onClose(); claimRewards(); }}>
                    <ListItemIcon>
                      <PaymentIcon fontSize="small" />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      <Trans>Claim Rewards</Trans>
                    </Typography>
                  </MenuItem>
                )}
              </PoolClaimRewards>
              <PoolJoin pool={pool}>
                {(join) => (
                  <MenuItem onClick={() => { onClose(); join(); }}>
                    <ListItemIcon>
                      <PowerIcon fontSize="small" />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      {pool.self 
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
  const pools = useSelector<PoolGroup[] | undefined>((state: RootState) => state.pool_group.pools);
  const loading = !pools;

  const totalWinning = useMemo<number>(
    () => pools && pools.length
      ? sumBy<PoolGroup>(pools, (item) => item.balance)
      : 0, 
    [pools],
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

  if (!pools) {
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
              + Add a Group
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
                Total Pool Winnings
              </Trans>
            </Typography>
            <UnitFormat value={totalWinning} state={State.SUCCESS} />
          </Flex>
        </Flex>
        {showTable ? (
          <Table
            rows={pools} 
            cols={poolsCols} 
          />
        ) : (
          <Grid spacing={3} alignItems="stretch" container>
            {pools.map((pool) => (
              <Grid key={pool.id} xs={12} md={6} item>
                <PoolCard pool={pool} />
              </Grid>
            ))}
          </Grid>
        )}
      </Flex>
    </Flex>
  );
}
