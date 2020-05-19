import React from "react";
import CssBaseline from "@material-ui/core/CssBaseline";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import { withRouter } from "react-router-dom";
import { connect, useSelector, useDispatch } from "react-redux";
import Typography from "@material-ui/core/Typography";
import Box from "@material-ui/core/Box";
import { Paper } from "@material-ui/core";
import { unix_to_short_date } from "../util/utils";
import Connections from "./Connections";
import Block from "./Block";
import { closeConnection, openConnection, getBlock, getHeader } from "../modules/fullnodeMessages";

/* global BigInt */

const drawerWidth = 180;

const useStyles = makeStyles(theme => ({
  root: {
    display: "flex",
    paddingLeft: "0px"
  },
  menuButton: {
    marginRight: 36
  },
  menuButtonHidden: {
    display: "none"
  },
  title: {
    flexGrow: 1
  },
  drawerPaper: {
    position: "relative",
    whiteSpace: "nowrap",
    width: drawerWidth,
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
    })
  },
  drawerPaperClose: {
    overflowX: "hidden",
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen
    }),
    width: theme.spacing(7),
    [theme.breakpoints.up("sm")]: {
      width: theme.spacing(9)
    }
  },
  content: {
    flexGrow: 1,
    height: "calc(100vh - 64px)",
    overflowX: "hidden"
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0)
  },
  paper: {
    padding: theme.spacing(0),
    display: "flex",
    overflow: "auto",
    flexDirection: "column"
  },
  fixedHeight: {
    height: 240
  },
  drawerWallet: {
    position: "relative",
    whiteSpace: "nowrap",
    width: drawerWidth,
    height: "100%",
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen
    })
  },
  balancePaper: {
    marginTop: theme.spacing(2)
  },
  bottomOptions: {
    position: "absolute",
    bottom: 0,
    width: "100%"
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1)
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1)
  },
  left_block_cell: {
    marginLeft: 10,
    width: "25%",
    textAlign: "left",
    overflowWrap: "break-word"
  },
  center_block_cell: {
    width: "25%",
    textAlign: "center",
    overflowWrap: "break-word"
  },
  center_block_cell_small: {
    width: "15%",
    textAlign: "center",
    overflowWrap: "break-word"
  },
  right_block_cell: {
    marginLeft: 30,
    marginRight: 10,
    width: "25%",
    textAlign: "right",
    overflowWrap: "break-word"
  },
  block_row: {
    height: "30px",
    borderBottom: "1px",
    cursor: "pointer",
    /* mouse over link */
    "&:hover": {
      backgroundColor: "#aaaaaa"
    }
  },
  block_row_unfinished: {
    height: "30px",
    borderBottom: "1px",
    color: "orange",
    "&:hover": {
      backgroundColor: "#aaaaaa"
    }
  },
  block_header: {
    marginBottom: 10
  }
}));

const getStatusItems = (state, connected) => {
  var status_items = [];
  if (state.sync && state.sync.sync_mode) {
    const progress = state.sync.sync_progress_height;
    const tip = state.sync.sync_tip_height;
    const item = { label: "Status", value: "Syncing " + progress + "/" + tip };
    status_items.push(item);
  } else {
    const item = { label: "Status", value: "Synced" };
    status_items.push(item);
  }

  if (state.lca) {
    const lca_height = state.lca.data.height;
    const item = { label: "LCA Block Height", value: "" + lca_height };
    status_items.push(item);
  } else {
    const item = { label: "LCA Block Height", value: "0" };
    status_items.push(item);
  }

  if (state.tips) {
    var max_height = 0;
    for (let tip of state.tips) {
      if (parseInt(tip.height) > max_height) {
        max_height = parseInt(tip.height);
      }
    }
    const item = { label: "Max Tip Block Height", value: "" + max_height };
    status_items.push(item);
  } else {
    const item = { label: "Max Tip Block Height", value: "0" };
    status_items.push(item);
  }

  if (state.lca) {
    const lca_time = state.lca.data.timestamp;
    const date_string = unix_to_short_date(parseInt(lca_time));
    const item = { label: "LCA Time", value: date_string };
    status_items.push(item);
  } else {
    const item = { label: "LCA Time", value: "" };
    status_items.push(item);
  }

  if (connected) {
    const item = { label: "Connection Status ", value: "connected" };
    status_items.push(item);
  } else {
    const item = { label: "Connection Status ", value: "not connected" };
    status_items.push(item);
  }
  const difficulty = state.difficulty;
  const diff_item = { label: "Difficulty", value: difficulty };
  status_items.push(diff_item);

  const ips = state.ips;
  const ips_item = { label: "Iterations per Second", value: ips };
  status_items.push(ips_item);

  const iters = state.min_iters;
  const min_item = { label: "Min Iterations", value: iters };
  status_items.push(min_item);

  const space = (BigInt(state.space) / BigInt(Math.pow(1024, 4))).toString() + "TB";
  const space_item = { label: "Estimated network space", value: space };
  status_items.push(space_item);

  return status_items;
};

const StatusCell = props => {
  const classes = useStyles();
  const item = props.item;
  const label = item.label;
  const value = item.value;
  return (
    <Grid item xs={6}>
      <div className={classes.cardSubSection}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Typography variant="subtitle1">{label}</Typography>
          </Box>
          <Box>
            <Typography variant="subtitle1">{value}</Typography>
          </Box>
        </Box>
      </div>
    </Grid>
  );
};
const FullNodeStatus = props => {
  const blockchain_state = useSelector(
    state => state.full_node_state.blockchain_state
  );
  const connected = useSelector(
    state => state.daemon_state.full_node_connected
  );
  const statusItems = getStatusItems(blockchain_state, connected);

  const classes = useStyles();
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Full Node Status
            </Typography>
          </div>
        </Grid>
        {statusItems.map(item => (
          <StatusCell item={item} key={item.label}></StatusCell>
        ))}
      </Grid>
    </Paper>
  );
};

const BlocksCard = () => {
  const headers = useSelector(state => state.full_node_state.headers);
  const dispatch = useDispatch();

  function clickedBlock(height, header_hash, prev_header_hash) {
    return () => {
      dispatch(getBlock(header_hash));
      if (height > 0) {
        dispatch(getHeader(prev_header_hash));
      }
    }
  }
  const classes = useStyles();
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Blocks
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <Box
            className={classes.block_header}
            display="flex"
            key={"header"}
            style={{ minWidth: "100%" }}
          >
            <Box className={classes.left_block_cell}>Header Hash</Box>
            <Box className={classes.center_block_cell_small}>Height</Box>
            <Box flexGrow={1} className={classes.center_block_cell}>
              Time Created
            </Box>
            <Box className={classes.right_block_cell}>Expected finish time</Box>
          </Box>
          {headers.map(header => (
            <Box
              className={header.data.finished ? classes.block_row : classes.block_row_unfinished}
              onClick={header.data.finished ? clickedBlock(header.data.height, header.data.header_hash, header.data.prev_header_hash) : () => {}}
              display="flex"
              key={header.data.header_hash}
              style={{ minWidth: "100%" }}
            >
              <Box className={classes.left_block_cell}>
                {header.data.header_hash.substring(0, 12) + "..."}
                {header.data.finished ? "" : " (unfinished)"}
              </Box>
              <Box className={classes.center_block_cell_small}>
                {header.data.height}
              </Box>
              <Box flexGrow={1} className={classes.center_block_cell}>
                {unix_to_short_date(parseInt(header.data.timestamp))}
              </Box>
              <Box className={classes.right_block_cell}>
                {header.data.finished
                  ? "finished"
                  : unix_to_short_date(parseInt(header.data.finish_time))}
              </Box>
            </Box>
          ))}
        </Grid>
      </Grid>
    </Paper>
  );
};

const SearchBlock = props => {
  const classes = useStyles();
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Search
            </Typography>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const FullNode = () => {
  const classes = useStyles();
  const dispatch = useDispatch();

  const connections = useSelector(
    state => state.full_node_state.connections
  );
  const connectionError = useSelector(
    state => state.full_node_state.open_connection_error
  );
  const block = useSelector(
    state => state.full_node_state.block
  );
  const header = useSelector(
    state => state.full_node_state.header
  );

  const openConnectionCallback = (host, port) => {
    dispatch(openConnection(host, port))
  }
  const closeConnectionCallback = (node_id) => {
    dispatch(closeConnection(node_id))
  }

  return (
    <div className={classes.root}>
      <CssBaseline />
      <main className={classes.content}>
        <Container maxWidth="lg" className={classes.container}>
          <Grid container spacing={3}>
          {block != null ? <Block block={block} prevHeader={header}></Block> : <span>
              <Grid item xs={12}>
                <FullNodeStatus></FullNodeStatus>
              </Grid>
              <Grid item xs={12}>
                <BlocksCard></BlocksCard>
              </Grid>
              <Grid item xs={12}>
                  <Connections connections={connections} connectionError={connectionError} openConnection={openConnectionCallback} closeConnection={closeConnectionCallback}></Connections>
              </Grid>
              <Grid item xs={12}>
                <SearchBlock></SearchBlock>
              </Grid>
            </span>}
          </Grid>
        </Container>
      </main>
    </div>
  );
};

export default withRouter(connect()(FullNode));
