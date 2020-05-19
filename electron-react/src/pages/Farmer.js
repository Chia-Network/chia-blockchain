import React from "react";
import CssBaseline from "@material-ui/core/CssBaseline";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import { withRouter } from "react-router-dom";
import { connect, useSelector, useDispatch } from "react-redux";
import Typography from "@material-ui/core/Typography";
import Box from "@material-ui/core/Box";
import {
  Paper,
  TableRow,
  Drawer,
  Divider,
  List,
  ListItem,
  ListItemText,
} from "@material-ui/core";
import Button from "@material-ui/core/Button";
import Table from "@material-ui/core/Table";
import TableBody from "@material-ui/core/TableBody";
import TableCell from "@material-ui/core/TableCell";
import TableContainer from "@material-ui/core/TableContainer";
import TableHead from "@material-ui/core/TableHead";
import DeleteForeverIcon from "@material-ui/icons/DeleteForever";

import { calculateSizeFromK } from "../util/plot_sizes";
import { closeConnection, openConnection } from "../modules/farmerMessages";
import { refreshPlots, deletePlot } from "../modules/harvesterMessages";

import TablePagination from "@material-ui/core/TablePagination";
import RefreshIcon from "@material-ui/icons/Refresh";
import Connections from "./Connections";

import Plotter from "./Plotter";
import { presentFarmer } from "../modules/farmer_menu";
import { presentPlotter, changeFarmerMenu } from "../modules/farmer_menu";

const drawerWidth = 180;

const useStyles = makeStyles((theme) => ({
  root: {
    display: "flex",
    paddingLeft: "0px",
  },
  tabs: {
    flexGrow: 1,
    marginTop: 40,
  },
  clickable: {
    cursor: "pointer",
  },
  refreshButton: {
    marginLeft: "20px",
  },
  content: {
    height: "calc(100vh - 64px)",
    overflowX: "hidden",
    paddingRight: theme.spacing(3),
    paddingBottom: theme.spacing(3),
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
  },
  balancePaper: {
    marginTop: theme.spacing(2),
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
  table: {
    minWidth: 650,
  },
  drawerPaper: {
    position: "relative",
    whiteSpace: "nowrap",
    width: drawerWidth,
    transition: theme.transitions.create("width", {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
}));

const getStatusItems = (connected, plots_size) => {
  var status_items = [];

  if (connected) {
    const item = { label: "Connection Status ", value: "connected" };
    status_items.push(item);
  } else {
    const item = { label: "Connection Status ", value: "not connected" };
    status_items.push(item);
  }
  status_items.push({
    label: "Total size of local plots",
    value: Math.floor(plots_size / Math.pow(1024, 3)).toString() + " GB",
  });
  return status_items;
};

const StatusCell = (props) => {
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

const FarmerStatus = (props) => {
  const plots = useSelector((state) => state.farming_state.harvester.plots);
  var total_size = 0;
  if (plots !== undefined) {
    total_size = plots
      .map((p) => calculateSizeFromK(p.size))
      .reduce((a, b) => a + b, 0);
  }

  const connected = useSelector((state) => state.daemon_state.farmer_connected);
  const statusItems = getStatusItems(connected, total_size);

  const classes = useStyles();
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Farmer Status
            </Typography>
          </div>
        </Grid>
        {statusItems.map((item) => (
          <StatusCell item={item} key={item.label}></StatusCell>
        ))}
      </Grid>
    </Paper>
  );
};

const Challenges = (props) => {
  const classes = useStyles();
  var latest_challenges = useSelector(
    (state) => state.farming_state.farmer.latest_challenges
  );

  if (!latest_challenges) {
    latest_challenges = [];
  }
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Challenges
            </Typography>
          </div>
          <TableContainer component={Paper}>
            <Table
              className={classes.table}
              size="small"
              aria-label="a dense table"
            >
              <TableHead>
                <TableRow>
                  <TableCell>Challange hash</TableCell>
                  <TableCell align="right">Height</TableCell>
                  <TableCell align="right">Number of proofs</TableCell>
                  <TableCell align="right">Best estimate</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {latest_challenges.map((item) => (
                  <TableRow key={item.challenge}>
                    <TableCell component="th" scope="row">
                      {item.challenge.substring(0, 10)}...
                    </TableCell>
                    <TableCell align="right">{item.height}</TableCell>
                    <TableCell align="right">{item.estimates.length}</TableCell>
                    <TableCell align="right">
                      {item.estimates.length > 0
                        ? Math.floor(
                            Math.min.apply(Math, item.estimates) / 60
                          ).toString() + " minutes"
                        : ""}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Grid>
      </Grid>
    </Paper>
  );
};

const Plots = (props) => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const plots = useSelector((state) => state.farming_state.harvester.plots);
  const not_found_filenames = useSelector(
    (state) => state.farming_state.harvester.not_found_filenames
  );
  const failed_to_open_filenames = useSelector(
    (state) => state.farming_state.harvester.failed_to_open_filenames
  );
  plots.sort((a, b) => b.size - a.size);
  const [page, setPage] = React.useState(0);
  const [rowsPerPage, setRowsPerPage] = React.useState(10);

  const handleChangePage = (event, newPage) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (event) => {
    setRowsPerPage(+event.target.value);
    setPage(0);
  };

  const deletePlotClick = (filename) => {
    return () => {
      dispatch(deletePlot(filename));
    };
  };

  const refreshPlotsClick = () => {
    dispatch(refreshPlots());
  };

  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Plots
              <Button
                variant="contained"
                color="primary"
                onClick={refreshPlotsClick}
                className={classes.refreshButton}
                startIcon={<RefreshIcon />}
              >
                Refresh plots
              </Button>
            </Typography>
          </div>

          <TableContainer component={Paper}>
            <Table
              className={classes.table}
              size="small"
              aria-label="a dense table"
            >
              <TableHead>
                <TableRow>
                  <TableCell>Filename</TableCell>
                  <TableCell align="right">Size</TableCell>
                  <TableCell align="right">Plot seed</TableCell>
                  <TableCell align="right">Plot pk</TableCell>
                  <TableCell align="right">Pool pk</TableCell>
                  <TableCell align="right">Delete</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {plots
                  .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
                  .map((item) => (
                    <TableRow key={item.filename}>
                      <TableCell component="th" scope="row">
                        {item.filename.substring(0, 60)}...
                      </TableCell>
                      <TableCell align="right">{item.size}</TableCell>
                      <TableCell align="right">
                        {item["plot-seed"].substring(0, 10)}
                      </TableCell>
                      <TableCell align="right">
                        {item.plot_pk.substring(0, 10)}...
                      </TableCell>
                      <TableCell align="right">
                        {item.pool_pk.substring(0, 10)}...
                      </TableCell>
                      <TableCell
                        className={classes.clickable}
                        onClick={deletePlotClick(item.filename)}
                        align="right"
                      >
                        <DeleteForeverIcon fontSize="small"></DeleteForeverIcon>
                      </TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            rowsPerPageOptions={[10, 25, 100]}
            component="div"
            count={plots.length}
            rowsPerPage={rowsPerPage}
            page={page}
            onChangePage={handleChangePage}
            onChangeRowsPerPage={handleChangeRowsPerPage}
          />

          {not_found_filenames.length > 0 ? (
            <span>
              <div className={classes.cardTitle}>
                <Typography component="h6" variant="h6">
                  Not found plots
                </Typography>
              </div>
              <List dense={classes.dense}>
                {not_found_filenames.map((filename) => (
                  <ListItem key={filename}>
                    <ListItemText primary={filename} />
                  </ListItem>
                ))}
              </List>{" "}
            </span>
          ) : (
            ""
          )}
          {failed_to_open_filenames.length > 0 ? (
            <span>
              <div className={classes.cardTitle}>
                <Typography component="h6" variant="h6">
                  Failed to open (invalid plots)
                </Typography>
              </div>
              <List dense={classes.dense}>
                {failed_to_open_filenames.map((filename) => (
                  <ListItem key={filename}>
                    <ListItemText primary={filename} />
                  </ListItem>
                ))}
              </List>
            </span>
          ) : (
            ""
          )}
        </Grid>
      </Grid>
    </Paper>
  );
};

const FarmerContent = () => {
  const classes = useStyles();
  const dispatch = useDispatch();

  const connections = useSelector(
    (state) => state.farming_state.farmer.connections
  );

  const connectionError = useSelector(
    (state) => state.farming_state.farmer.open_connection_error
  );

  const openConnectionCallback = (host, port) => {
    dispatch(openConnection(host, port));
  };
  const closeConnectionCallback = (node_id) => {
    dispatch(closeConnection(node_id));
  };

  const to_present = useSelector((state) => state.farmer_menu.view);

  if (to_present === presentFarmer) {
    return (
      <Container maxWidth="lg" className={classes.container}>
        <Grid container spacing={3}>
          {/* Chart */}
          <Grid item xs={12}>
            <FarmerStatus></FarmerStatus>
          </Grid>
          <Grid item xs={12}>
            <Challenges></Challenges>
          </Grid>
          <Grid item xs={12}>
            <Connections
              connections={connections}
              connectionError={connectionError}
              openConnection={openConnectionCallback}
              closeConnection={closeConnectionCallback}
            ></Connections>
          </Grid>
          <Grid item xs={12}>
            <Plots></Plots>
          </Grid>
        </Grid>
      </Container>
    );
  } else {
    return <Plotter></Plotter>;
  }
};

const FarmerListItem = (props) => {
  const dispatch = useDispatch();
  const label = props.label;
  const type = props.type;
  function present() {
    if (type === presentFarmer) {
      dispatch(changeFarmerMenu(presentFarmer));
    } else if (type === presentPlotter) {
      dispatch(changeFarmerMenu(presentPlotter));
    }
  }

  return (
    <ListItem button onClick={present}>
      <ListItemText primary={label} />
    </ListItem>
  );
};

const FarmerMenuList = () => {
  return (
    <List>
      <FarmerListItem
        label="Farmer & Harvester"
        type={presentFarmer}
      ></FarmerListItem>
      <Divider />
      <FarmerListItem label="Plotter" type={presentPlotter}></FarmerListItem>
      <Divider />
    </List>
  );
};

const Farmer = () => {
  const classes = useStyles();
  var open = true;
  return (
    <div className={classes.root}>
      <CssBaseline />
      <Drawer
        variant="permanent"
        classes={{
          paper: classes.drawerPaper,
        }}
        open={open}
      >
        <FarmerMenuList></FarmerMenuList>
      </Drawer>
      <main className={classes.content}>
        <Container maxWidth="lg" className={classes.container}>
          <FarmerContent></FarmerContent>
        </Container>
      </main>
    </div>
  );
};

export default withRouter(connect()(Farmer));
