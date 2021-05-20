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
import type Group from '../../types/Group';
import PoolCard from '../group/GroupCard';
import GroupName from '../group/GroupName';
import GroupStatus from '../Group/GroupStatus';
import PoolWalletStatus from '../wallet/WalletStatus';
import PoolClaimRewards from '../group/GroupClaimRewards';
import PoolJoin from './PoolJoin';
import PoolHero from './PoolHero';

const groupsCols = [
  {
    field: (group: Group) => <GroupName group={group} />,
    title: <Trans>Pool Name: URL</Trans>,
  },
  {
    field: () => <PoolWalletStatus />,
    title: <Trans>Wallet Status</Trans>,
  },
  {
    field: (group: Group) => <GroupStatus group={group} />,
    title: <Trans>Pool Status</Trans>,
  },
  {
    field: (group: Group) => <UnitFormat value={group.balance} />,
    title: <Trans>Pool Winnings</Trans>,
  },
  {
    title: <Trans>Actions</Trans>,
    field(group: Group) {
      return (
        <More>
          {({ onClose }) => (
            <Box>
              <PoolClaimRewards group={group}>
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
              <PoolJoin group={group}>
                {(join) => (
                  <MenuItem onClick={() => { onClose(); join(); }}>
                    <ListItemIcon>
                      <PowerIcon fontSize="small" />
                    </ListItemIcon>
                    <Typography variant="inherit" noWrap>
                      {group.self 
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
  const groups = useSelector<Group[] | undefined>((state: RootState) => state.group.groups);
  const loading = !groups;

  const totalWinning = useMemo<number>(
    () => groups && groups.length
      ? sumBy<Group>(groups, (item) => item.balance)
      : 0, 
    [groups],
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

  if (!groups) {
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
            rows={groups} 
            cols={groupsCols} 
          />
        ) : (
          <Grid spacing={3} alignItems="stretch" container>
            {groups.map((group) => (
              <Grid key={group.id} xs={12} md={6} item>
                <PoolCard group={group} />
              </Grid>
            ))}
          </Grid>
        )}
      </Flex>
    </Flex>
  );
}
