import React from 'react';
import { Trans } from '@lingui/macro';
import { get } from 'lodash';
import {
  FormatBytes,
  Flex,
  Card,
  Loading,
  StateColor,
  Table,
} from '@chia/core';
import { Status } from '@chia/icons';
import { useRouteMatch, useHistory } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { Box, Grid, Tooltip, Typography } from '@material-ui/core';
import HelpIcon from '@material-ui/icons/Help';
import { unix_to_short_date } from '../../util/utils';
import FullNodeConnections from './FullNodeConnections';
import LayoutMain from '../layout/LayoutMain';
import FullNodeBlockSearch from './FullNodeBlockSearch';

/* global BigInt */

const cols = [
  {
    minWidth: '250px',
    field(row) {
      const { isFinished = false, header_hash, foliage } = row;

      const { foliage_transaction_block_hash } = foliage || {};

      const value = isFinished ? (
        header_hash
      ) : (
        <span>{foliage_transaction_block_hash}</span>
      );

      const color = isFinished ? StateColor.SUCCESS : StateColor.WARNING;

      const tooltip = isFinished ? (
        <Trans>Finished</Trans>
      ) : (
        <Trans>In Progress</Trans>
      );

      return (
        <Flex gap={1} alignItems="center">
          <Tooltip title={<span>{tooltip}</span>}>
            <Status color={color} />
          </Tooltip>
          <Tooltip title={<span>{value}</span>}>
            <Box textOverflow="ellipsis" overflow="hidden">
              {value}
            </Box>
          </Tooltip>
        </Flex>
      );
    },
    title: <Trans>Header Hash</Trans>,
  },
  {
    field(row) {
      const { isFinished, foliage } = row;

      const { height: foliageHeight } = foliage || {};

      const height = get(row, 'reward_chain_block.height');

      if (!isFinished) {
        return <i>{foliageHeight}</i>;
      }

      return height;
    },
    title: <Trans>Height</Trans>,
  },
  {
    field(row) {
      const { isFinished } = row;

      const timestamp = get(row, 'foliage_transaction_block.timestamp');
      const value = timestamp;

      return value ? unix_to_short_date(Number.parseInt(value)) : '';
    },
    title: <Trans>Time Created</Trans>,
  },
  {
    field(row) {
      const { isFinished = false } = row;

      return isFinished ? <Trans>Finished</Trans> : <Trans>Unfinished</Trans>;
    },
    title: <Trans>State</Trans>,
  },
];

const getStatusItems = (state, connected, latestPeakTimestamp, networkInfo) => {
  const status_items = [];
  if (state.sync && state.sync.sync_mode) {
    const progress = state.sync.sync_progress_height;
    const tip = state.sync.sync_tip_height;
    const item = {
      label: <Trans>Status</Trans>,
      value: (
        <Trans>
          Syncing {progress}/{tip}
        </Trans>
      ),
      colour: 'orange',
      tooltip: (
        <Trans>
          The node is syncing, which means it is downloading blocks from other
          nodes, to reach the latest block in the chain
        </Trans>
      ),
    };
    status_items.push(item);
  } else if (!state.sync.synced) {
    const item = {
      label: <Trans>Status</Trans>,
      value: <Trans>Not Synced</Trans>,
      colour: 'red',
      tooltip: <Trans>The node is not synced</Trans>,
    };
    status_items.push(item);
  } else {
    const item = {
      label: <Trans>Status</Trans>,
      value: <Trans>Synced</Trans>,
      colour: '#3AAC59',
      tooltip: (
        <Trans>This node is fully caught up and validating the network</Trans>
      ),
    };
    status_items.push(item);
  }

  if (connected) {
    status_items.push({
      label: <Trans>Connection Status</Trans>,
      value: connected ? (
        <Trans>Connected</Trans>
      ) : (
        <Trans>Not connected</Trans>
      ),
      colour: connected ? '#3AAC59' : 'red',
    });
  } else {
    const item = {
      label: <Trans>Status</Trans>,
      value: <Trans>Not connected</Trans>,
      colour: 'black',
    };
    status_items.push(item);
  }

  const networkName = networkInfo?.network_name;
  status_items.push({
    label: <Trans>Network Name</Trans>,
    value: networkName,
  });

  const peakHeight = state.peak?.height ?? 0;
  status_items.push({
    label: <Trans>Peak Height</Trans>,
    value: peakHeight,
  });

  status_items.push({
    label: <Trans>Peak Time</Trans>,
    value: latestPeakTimestamp ? unix_to_short_date(latestPeakTimestamp) : '',
    tooltip: <Trans>This is the time of the latest peak sub block.</Trans>,
  });

  const { difficulty } = state;
  const diff_item = {
    label: <Trans>Difficulty</Trans>,
    value: difficulty,
  };
  status_items.push(diff_item);

  const { sub_slot_iters } = state;
  status_items.push({
    label: <Trans>VDF Sub Slot Iterations</Trans>,
    value: sub_slot_iters,
  });

  const totalIters = state.peak?.total_iters ?? 0;
  status_items.push({
    label: <Trans>Total Iterations</Trans>,
    value: totalIters,
    tooltip: <Trans>Total iterations since the start of the blockchain</Trans>,
  });

  const space_item = {
    label: <Trans>Estimated network space</Trans>,
    value: <FormatBytes value={state.space} precision={3} />,
    tooltip: (
      <Trans>
        Estimated sum of all the plotted disk space of all farmers in the
        network
      </Trans>
    ),
  };
  status_items.push(space_item);

  return status_items;
};

const StatusCell = (props) => {
  const { item } = props;
  const { label } = item;
  const { value } = item;
  const { tooltip } = item;
  const { colour } = item;
  return (
    <Grid item xs={12} md={6}>
      <Flex mb={-2} alignItems="center">
        <Flex flexGrow={1} gap={1} alignItems="center">
          <Typography variant="subtitle1">{label}</Typography>
          {tooltip && (
            <Tooltip title={tooltip}>
              <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
            </Tooltip>
          )}
        </Flex>
        <Typography variant="subtitle1">
          <span style={colour ? { color: colour } : {}}>{value}</span>
        </Typography>
      </Flex>
    </Grid>
  );
};

const FullNodeStatus = (props) => {
  const blockchainState = useSelector(
    (state) => state.full_node_state.blockchain_state,
  );
  const connected = useSelector(
    (state) => state.daemon_state.full_node_connected,
  );

  const latestPeakTimestamp = useSelector(
    (state) => state.full_node_state.latest_peak_timestamp,
  );

  const networkInfo = useSelector(
    (state) => state.wallet_state.network_info,
  );

  const statusItems = blockchainState && getStatusItems(blockchainState, connected, latestPeakTimestamp, networkInfo);

  return (
    <Card title={<Trans>Full Node Status</Trans>}>
      {statusItems ? (
        <Grid spacing={4} container>
          {statusItems.map((item) => (
            <StatusCell item={item} key={item.label.props.id} />
          ))}
        </Grid>
      ) : (
        <Flex justifyContent="center">
          <Loading />
        </Flex>
      )}
    </Card>
  );
};

const BlocksCard = () => {
  const { url } = useRouteMatch();
  const history = useHistory();
  const latestBlocks = useSelector(
    (state) => state.full_node_state.latest_blocks ?? [],
  );
  const unfinishedBlockHeaders = useSelector(
    (state) => state.full_node_state.unfinished_block_headers ?? [],
  );

  const rows = [
    ...unfinishedBlockHeaders,
    ...latestBlocks.map((row) => ({
      ...row,
      isFinished: true,
    })),
  ];

  function handleRowClick(event, row) {
    const { isFinished, header_hash } = row;

    if (isFinished && header_hash) {
      history.push(`${url}/block/${header_hash}`);
    }
  }

  return (
    <Card title={<Trans>Blocks</Trans>} action={<FullNodeBlockSearch />}>
      {rows.length ? (
        <Table cols={cols} rows={rows} onRowClick={handleRowClick} />
      ) : (
        <Flex justifyContent="center">
          <Loading />
        </Flex>
      )}
    </Card>
  );
};

export default function FullNode() {
  return (
    <LayoutMain title={<Trans>Full Node</Trans>}>
      <Flex flexDirection="column" gap={3}>
        <FullNodeStatus />
        <BlocksCard />
        <FullNodeConnections />
      </Flex>
    </LayoutMain>
  );
}
