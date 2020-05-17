import React from "react";
import CssBaseline from "@material-ui/core/CssBaseline";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import { withRouter, Redirect } from "react-router-dom";
import { connect, useDispatch, useSelector } from "react-redux";
import clsx from "clsx";
import Drawer from "@material-ui/core/Drawer";
import List from "@material-ui/core/List";
import Typography from "@material-ui/core/Typography";
import Divider from "@material-ui/core/Divider";
import Box from "@material-ui/core/Box";
import { mojo_to_chia_string } from "../util/chia";
import { Paper } from "@material-ui/core";
import { unix_to_short_date } from "../util/utils";

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
  }
}));

const getSatusItems = (state, connected) => {
  var status_items = [];
  if (state.sync.sync_mode) {
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
    state.tips.map(tip => {
      if (parseInt(tip.height) > max_height) {
        max_height = parseInt(tip.height);
      }
    });
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
  var id = props.wallet_id;
  const balance = 0;
  const balance_pending = 0;
  const blockchain_state = useSelector(
    state => state.full_node_state.blockchain_state
  );
  const connected = useSelector(
    state => state.daemon_state.full_node_connected
  );
  const statusItems = getSatusItems(blockchain_state, connected);

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
          <StatusCell item={item}></StatusCell>
        ))}
      </Grid>
    </Paper>
  );
};

const BlocksCard = props => {
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
      </Grid>
    </Paper>
  );
};

const Connections = props => {
  const classes = useStyles();
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Connections
            </Typography>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const Control = props => {
  const classes = useStyles();
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Control
            </Typography>
          </div>
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

  return (
    <div className={classes.root}>
      <CssBaseline />
      <main className={classes.content}>
        <Container maxWidth="lg" className={classes.container}>
          <Grid container spacing={3}>
            {/* Chart */}
            <Grid item xs={12}>
              <FullNodeStatus></FullNodeStatus>
            </Grid>
            <Grid item xs={12}>
              <Control></Control>
            </Grid>
            <Grid item xs={12}>
              <BlocksCard></BlocksCard>
            </Grid>
            <Grid item xs={12}>
              <Connections></Connections>
            </Grid>
            <Grid item xs={12}>
              <SearchBlock></SearchBlock>
            </Grid>
          </Grid>
        </Container>
      </main>
    </div>
  );
};

export default withRouter(connect()(FullNode));
