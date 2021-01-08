import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { FormatBytes, Flex, Card, Loading, Table } from '@chia/core';
import { Status } from '@chia/icons';
import { useRouteMatch, useHistory } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { Box, Button, Grid, TextField, Tooltip, Typography } from '@material-ui/core';
import HelpIcon from '@material-ui/icons/Help';
import { unix_to_short_date } from '../../util/utils';
import FullNodeConnections from './FullNodeConnections';
import {
  closeConnection,
  openConnection,
} from '../../modules/fullnodeMessages';
import LayoutMain from '../layout/LayoutMain';
import StateColor from '../../constants/StateColor';

/* global BigInt */

const cols = [
  {
    minWidth: '200px',
    field(row) {
      const {
        isFinished = false,
        header_hash,
        foliage_sub_block: {
          foliage_block_hash,
        },
      } = row;

      const value = isFinished 
        ? header_hash
        : <span>{foliage_block_hash}</span>;

      const color = isFinished
        ? StateColor.SUCCESS
        : StateColor.WARNING;

      const tooltip = isFinished
        ? <Trans id="BlocksCard.finished">Finished</Trans>
        : <Trans id="BlocksCard.inProgress">In Progress</Trans>;

      return (
        <Flex gap={1} alignItems="center">
          <Tooltip title={<span>{tooltip}</span>}>
            <Status color={color} />
          </Tooltip>
          <span>{value}</span>
        </Flex>
      )
    },
    title: <Trans id="BlocksCard.headerHash">Header Hash</Trans>,
  },/*
  {
    width: '120px',
    field: 'foliage_sub_block.height',
    title: <Trans id="BlocksCard.sbHeight">SB Height</Trans>,
  },*/
  {
    width: '120px',
    field: 'foliage_block.height',
    title: <Trans id="BlocksCard.height">Height</Trans>,
  },
  {
    width: '180px',
    field(row) {
      const {
        foliage_block: {
          timestamp,
        },
      } = row;
      return unix_to_short_date(Number.parseInt(timestamp));
    },
    title: <Trans id="BlocksCard.timeCreated">Time Created</Trans>,
  },
  {
    width: '130px',
    field(row) {
      const {
        isFinished = false,
      } = row;

      return isFinished
        ? <Trans id="BlocksCard.finished">Finished</Trans>
        : <Trans id="BlocksCard.unfinished">Unfinished</Trans>;
    },
    title: (
      <Trans id="BlocksCard.state">
        State
      </Trans>
    ),
  },
];

const getStatusItems = (state, connected) => {
  const status_items = [];
  if (state.sync && state.sync.sync_mode) {
    const progress = state.sync.sync_progress_sub_height;
    const tip = state.sync.sync_tip_sub_height;
    const item = {
      label: <Trans id="StatusItem.status">Status</Trans>,
      value: (
        <Trans id="StatusItem.statusValue">
          Syncing {progress}/{tip}
        </Trans>
      ),
      colour: 'orange',
      tooltip: (
        <Trans id="StatusItem.statusTooltip">
          The node is syncing, which means it is downloading blocks from other
          nodes, to reach the latest block in the chain
        </Trans>
      ),
    };
    status_items.push(item);
  } else if (!state.sync.synced){
    const item = {
      label: <Trans id="StatusItem.status">Status</Trans>,
      value: (
        <Trans id="StatusItem.statusNotSynced">
          Not Synced
        </Trans>
      ),
      colour: 'red',
      tooltip: (
        <Trans id="StatusItem.statusNotSyncedTooltip">
          The node is not synced
        </Trans>
      ),
    };
    status_items.push(item);
  } else {
    const item = {
      label: <Trans id="StatusItem.status">Status</Trans>,
      value: <Trans id="StatusItem.statusSynced">Synced</Trans>,
      colour: '#3AAC59',
      tooltip: (
        <Trans id="StatusItem.statusSyncedTooltip">
          This node is fully caught up and validating the network
        </Trans>
      ),
    };
    status_items.push(item);
  }

  if (connected) {
    status_items.push({
      label: <Trans id="StatusItem.connectionStatus">Connection Status</Trans>,
      value: connected ? (
        <Trans id="StatusItem.connectionStatusConnected">Connected</Trans>
      ) : (
        <Trans id="StatusItem.connectionStatusNotConnected">
          Not connected
        </Trans>
      ),
      colour: connected ? '#3AAC59' : 'red',
    });
  } else {
    const item = {
      label: <Trans id="StatusItem.status">Status</Trans>,
      value: <Trans id="StatusItem.statusNotConnected">Not connected</Trans>,
      colour: 'black',
    };
    status_items.push(item);
  }

  const peakHeight = state.peak?.foliage_block?.height ?? 0;
  status_items.push({
    label: <Trans id="StatusItem.peakHeight">Peak Height</Trans>,
    value: peakHeight,
  });

  const peakSubBlockHeight = state.peak?.reward_chain_sub_block?.sub_block_height ?? 0;
  status_items.push({
    label: <Trans id="StatusItem.peakSubBlockHeight">Peak Sub-block Height</Trans>,
    value: peakSubBlockHeight,
  });

  const peakTimestamp = state.peak?.foliage_block?.timestamp;
  status_items.push({
    label: <Trans id="StatusItem.peakTime">Peak Time</Trans>,
    value: peakTimestamp
      ? unix_to_short_date(Number.parseInt(peakTimestamp))
      : '',
    tooltip: (
      <Trans id="StatusItem.peakTimeTooltip">
        This is the time of the latest peak sub block.
      </Trans>
    ),
  });

  const { difficulty } = state;
  const diff_item = {
    label: <Trans id="StatusItem.difficulty">Difficulty</Trans>,
    value: difficulty,
  };
  status_items.push(diff_item);

  const { sub_slot_iters } = state;
  status_items.push({
    label: (
      <Trans id="StatusItem.subSlotIters">VDF Sub Slot Iterations</Trans>
    ),
    value: sub_slot_iters,
  });

  const totalIters = state.peak?.reward_chain_sub_block?.total_iters ?? 0;
  status_items.push({
    label: (
      <Trans id="StatusItem.totalIterations">Total Iterations</Trans>
    ),
    value: totalIters,
    tooltip: (
      <Trans id="StatusItem.totalIterationsTooltip">
        Total iterations since the start of the blockchain
      </Trans>
    ),
  });

  const space_item = {
    label: (
      <Trans id="StatusItem.estimatedNetworkSpace">
        Estimated network space
      </Trans>
    ),
    value: <FormatBytes value={state.space} precision={3} />,
    tooltip: (
      <Trans id="StatusItem.estimatedNetworkSpaceTooltip">
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
  const blockchain_state = useSelector(
    (state) => state.full_node_state.blockchain_state,
  );
  const connected = useSelector(
    (state) => state.daemon_state.full_node_connected,
  );
  const statusItems = blockchain_state && getStatusItems(blockchain_state, connected);

  return (
    <Card
      title={<Trans id="FullNodeStatus.title">Full Node Status</Trans>}
    >
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
  const latestBlocks = useSelector((state) => state.full_node_state.latest_blocks ?? []);
  const unfinishedSubBlockHeaders = useSelector((state) => state.full_node_state.unfinished_sub_block_headers ?? []);

  const rows = [
    ...unfinishedSubBlockHeaders,
    ...latestBlocks.map(row => ({
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
    <Card
      title={<Trans id="BlocksCard.title">Blocks</Trans>}
    >
      {!!rows.length ? (
        <Table
          cols={cols}
          rows={rows}
          onRowClick={handleRowClick}
        />
      ) : (
        <Flex justifyContent="center">
          <Loading />
        </Flex>
      )}
    </Card>
  );
};

function SearchBlock() {
  const history = useHistory();
  const [searchHash, setSearchHash] = useState('');

  function handleChangeSearchHash(event) {
    setSearchHash(event.target.value);
  }

  function handleSearch() {
    history.push(`/dashboard/block/${searchHash}`);
    setSearchHash('');
  }

  return (
    <Card
      title={<Trans id="SearchBlock.title">Search block by header hash</Trans>}
    >
      <Flex alignItems="stretch">
        <Box flexGrow={1}>
          <TextField
            fullWidth
            label={<Trans id="SearchBlock.blockHash">Block hash</Trans>}
            value={searchHash}
            onChange={handleChangeSearchHash}
            variant="outlined"
          />
        </Box>
        <Button
          onClick={handleSearch}
          variant="contained"
          disableElevation
        >
          <Trans id="SearchBlock.search">Search</Trans>
        </Button>
      </Flex>
    </Card>
  );
}

export default function FullNode() {
  const dispatch = useDispatch();

  const connections = useSelector((state) => state.full_node_state.connections);
  const connectionError = useSelector(
    (state) => state.full_node_state.open_connection_error,
  );

  const openConnectionCallback = (host, port) => {
    dispatch(openConnection(host, port));
  };
  const closeConnectionCallback = (node_id) => {
    dispatch(closeConnection(node_id));
  };

  return (
    <LayoutMain
      title={<Trans id="FullNode.title">Full Node</Trans>}
    >
      <Flex flexDirection="column" gap={3}>
        <FullNodeStatus />
        <BlocksCard />
        <FullNodeConnections
          connections={connections}
          connectionError={connectionError}
          openConnection={openConnectionCallback}
          closeConnection={closeConnectionCallback}
        />
        <SearchBlock />
      </Flex>
    </LayoutMain>
  );
}
