import React, { useState, useEffect } from 'react';
import { Trans } from '@lingui/macro';
import { FormatBytes, Flex, Card, Loading } from '@chia/core';
import Grid from '@material-ui/core/Grid';
import { Switch, Route, Link, useRouteMatch } from 'react-router-dom'; 
import { makeStyles } from '@material-ui/core/styles';
import { useSelector, useDispatch } from 'react-redux';
import { Box, Button, TextField, Tooltip, Typography } from '@material-ui/core';
import HelpIcon from '@material-ui/icons/Help';
import { unix_to_short_date } from '../../util/utils';
import FullNodeConnections from './FullNodeConnections';
import Block from '../block/Block';
import {
  closeConnection,
  openConnection,
  getSubBlock,
  getSubBlockRecord,
  getSubBlockRecords,
} from '../../modules/fullnodeMessages';
import LayoutMain from '../layout/LayoutMain';

/* global BigInt */

const drawerWidth = 180;

const useStyles = makeStyles((theme) => ({
  menuButton: {
    marginRight: 36,
  },
  searchHashButton: {
    marginLeft: '10px',
    height: '100%',
  },
  menuButtonHidden: {
    display: 'none',
  },
  title: {
    flexGrow: 1,
  },
  drawerPaper: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  drawerPaperClose: {
    overflowX: 'hidden',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
    width: theme.spacing(7),
    [theme.breakpoints.up('sm')]: {
      width: theme.spacing(9),
    },
  },
  content: {
    flexGrow: 1,
    height: 'calc(100vh - 64px)',
    overflowX: 'hidden',
  },
  container: {
    paddingTop: theme.spacing(3),
    paddingLeft: theme.spacing(6),
    paddingRight: theme.spacing(6),
    paddingBottom: theme.spacing(3),
  },
  paper: {
    padding: theme.spacing(0),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
  },
  fixedHeight: {
    height: 240,
  },
  drawerWallet: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    height: '100%',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  balancePaper: {
    padding: theme.spacing(2),
    marginTop: theme.spacing(2),
  },
  bottomOptions: {
    position: 'absolute',
    bottom: 0,
    width: '100%',
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1),
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1),
  },
  left_block_cell: {
    marginLeft: 10,
    width: '25%',
    textAlign: 'left',
    overflowWrap: 'break-word',
  },
  center_block_cell: {
    width: '25%',
    textAlign: 'center',
    overflowWrap: 'break-word',
  },
  center_block_cell_small: {
    width: '15%',
    textAlign: 'center',
    overflowWrap: 'break-word',
  },
  right_block_cell: {
    marginLeft: 30,
    marginRight: 10,
    width: '25%',
    textAlign: 'right',
    overflowWrap: 'break-word',
  },
  block_row: {
    height: '30px',
    cursor: 'pointer',
    borderBottom: '1px solid #eeeeee',
    /* mouse over link */
    '&:hover': {
      // backgroundColor: "#eeeeee"
    },
  },
  block_row_unfinished: {
    height: '30px',
    borderBottom: '1px solid #eeeeee',
    color: 'orange',
  },
  block_header: {
    marginBottom: 10,
  },
}));

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
          The node is not synced and currently not syncing
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
        This is the time of the latest common ancestor, which is a block
        ancestor of all tip blocks. Note that the full node keeps track of up
        to three tips at each height.
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

  const totalIters = state.peak?.total_iters ?? 0;
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
    <Grid item xs={12} sm={6}>
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
  const { path, url } = useRouteMatch();
  const classes = useStyles();
  const dispatch = useDispatch();
  const latestBlocks = useSelector((state) => state.full_node_state.latest_blocks);
  const unfinishedSubBlockHeaders = useSelector((state) => state.full_node_state.unfinished_sub_block_headers);

  function handleShowBlock(record) {
    const {
      header_hash,
      foliage_block: {
        height,
        timestamp,
        prev_block_hash,
      },
    } = record;


  }

  function clickedBlock(height, header_hash, prev_header_hash) {
    return () => {
      dispatch(getSubBlock(header_hash));
      if (height > 0) {
        dispatch(getSubBlockRecord(prev_header_hash));
      }
    };
  }

  return (
    <Card
      title={<Trans id="BlocksCard.title">Blocks</Trans>}
    >
      {latestBlocks ? (
        <>
          <Box
            className={classes.block_header}
            display="flex"
            key="header"
            style={{ minWidth: '100%' }}
          >
            <Box className={classes.left_block_cell}>
              <Trans id="BlocksCard.headerHash">Header Hash</Trans>
            </Box>
            <Box className={classes.center_block_cell_small}>
              <Trans id="BlocksCard.height">Height</Trans>
            </Box>
            <Box flexGrow={1} className={classes.center_block_cell}>
              <Trans id="BlocksCard.timeCreated">Time Created</Trans>
            </Box>
            <Box className={classes.right_block_cell}>
              <Trans id="BlocksCard.expectedFinishTime">
                Expected finish time
              </Trans>
            </Box>
          </Box>

          {latestBlocks.map((record) => {
            const isFinished = true; //record.finished_reward_slot_hashes && !!record.finished_reward_slot_hashes.length;
            const {
              header_hash,
              foliage_block: {
                height,
                timestamp,
                prev_block_hash,
              }
            } = record;

            return (
              <Link to={`${url}/${header_hash}`}>
                <Box
                  className={
                    isFinished
                      ? classes.block_row
                      : classes.block_row_unfinished
                  }
                  display="flex"
                  key={header_hash}
                  style={{ minWidth: '100%' }}
                >
                  <Box className={classes.left_block_cell}>
                    {`${header_hash.slice(0, 12)}...`}
                    {isFinished ? '' : ' (unfinished)'}
                  </Box>
                  <Box className={classes.center_block_cell_small}>
                    {height}
                  </Box>
                  <Box flexGrow={1} className={classes.center_block_cell}>
                    {unix_to_short_date(Number.parseInt(timestamp))}
                  </Box>
                  <Box className={classes.right_block_cell}>
                    {isFinished
                      ? 'finished'
                      : unix_to_short_date(Number.parseInt(timestamp))}
                  </Box>
                </Box>
              </Link>
            );
          })}
        </>
      ) : (
        <Flex justifyContent="center">
          <Loading />
        </Flex>
      )}
    </Card>
  );
};

const SearchBlock = (props) => {
  const dispatch = useDispatch();
  const [searchHash, setSearchHash] = React.useState('');
  const handleChangeSearchHash = (event) => {
    setSearchHash(event.target.value);
  };
  const clickSearch = () => {
    setSearchHash('');
    dispatch(getBlock(searchHash));
  };
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
          onClick={clickSearch}
          variant="contained"
          disableElevation
        >
          <Trans id="SearchBlock.search">Search</Trans>
        </Button>
      </Flex>
    </Card>
  );
};

export default function FullNode() {
  const dispatch = useDispatch();
  const { path, url } = useRouteMatch();

  const connections = useSelector((state) => state.full_node_state.connections);
  const connectionError = useSelector(
    (state) => state.full_node_state.open_connection_error,
  );

  const block = useSelector((state) => state.full_node_state.block);
  const header = useSelector((state) => state.full_node_state.header);

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
        <Switch>
          <Route path={path} exact>
            <FullNodeStatus />
            <BlocksCard />
            <FullNodeConnections
              connections={connections}
              connectionError={connectionError}
              openConnection={openConnectionCallback}
              closeConnection={closeConnectionCallback}
            />
            <SearchBlock />
          </Route>
          <Route path={`${path}/:headerHash`}>
            <Block />
          </Route>
        </Switch>
      </Flex>
    </LayoutMain>
  );
}
