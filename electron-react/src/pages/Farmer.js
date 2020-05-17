import React from "react";
import CssBaseline from "@material-ui/core/CssBaseline";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import { withRouter } from "react-router-dom";
import { connect, useSelector, useDispatch } from "react-redux";
import Typography from "@material-ui/core/Typography";
import Box from "@material-ui/core/Box";
import { Paper, TableRow } from "@material-ui/core";
import Tabs from '@material-ui/core/Tabs';
import Tab from '@material-ui/core/Tab';
import Button from '@material-ui/core/Button';
import Table from '@material-ui/core/Table';
import TableBody from '@material-ui/core/TableBody';
import TableCell from '@material-ui/core/TableCell';
import TableContainer from '@material-ui/core/TableContainer';
import TableHead from '@material-ui/core/TableHead';
import DeleteForeverIcon from '@material-ui/icons/DeleteForever';

import DonutLargeIcon from "@material-ui/icons/DonutLarge";
import HourglassEmptyIcon from '@material-ui/icons/HourglassEmpty';
import { unix_to_short_date } from "../util/utils";
import { service_connection_types } from "../util/service_names";
import { calculateSizeFromK } from "../util/plot_sizes";
import { closeConnection, openConnection } from "../modules/farmerMessages";
import { refreshPlots, deletePlot } from "../modules/harvesterMessages";
import TextField from '@material-ui/core/TextField';
import SettingsInputAntennaIcon from '@material-ui/icons/SettingsInputAntenna';
import TablePagination from '@material-ui/core/TablePagination';
import RefreshIcon from '@material-ui/icons/Refresh';


const drawerWidth = 180;

const useStyles = makeStyles(theme => ({
  root: {
    display: "flex",
    paddingLeft: "0px"
  },
  tabs: {
    flexGrow: 1,
  },
  form : {
    margin: theme.spacing(1),
  },
  clickable: {
    cursor: "pointer"
  },
  error: {
    color: "red"
  },
  refreshButton: {
    marginLeft: "20px",
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
  table: {
    minWidth: 650,
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
  status_items.push({label: "Total size of local plots", value: Math.floor(plots_size / (Math.pow(1024, 3))).toString() + " GB"})
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

const FarmerStatus = props => {
  const plots = useSelector(
    state => state.farming_state.harvester.plots
  )

  const total_size = plots.map((p) => calculateSizeFromK(p.size)).reduce((a, b) => a + b, 0)

  const connected = useSelector(
    state => state.daemon_state.farmer_connected
  );
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
        {statusItems.map(item => (
          <StatusCell item={item} key={item.label}></StatusCell>
        ))}
      </Grid>
    </Paper>
  );
};

const Connections = props => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const connections = useSelector(
    state => state.farming_state.farmer.connections
  );
  const connection_error = useSelector(
    state => state.farming_state.farmer.open_connection_error
  )
  const [host, setHost] = React.useState('');
  const handleChangeHost = (event) => {
    setHost(event.target.value);
  };

  const [port, setPort] = React.useState('');
  const handleChangePort = (event) => {
    setPort(event.target.value);
  };

  const deleteConnection = (node_id) => {
    return () => {
      dispatch(closeConnection(node_id));
    }
  }
  const connectToPeer = () => {
    dispatch(openConnection(host, port));
    setHost("");
    setPort("");
  }

  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Connections
            </Typography>
          </div>
        <TableContainer component={Paper}>
          <Table className={classes.table} size="small" aria-label="a dense table">
            <TableHead>
              <TableRow>
                <TableCell>Node Id</TableCell>
                <TableCell align="right">Ip address</TableCell>
                <TableCell align="right">Port</TableCell>
                <TableCell align="right">Connected</TableCell>
                <TableCell align="right">Last message</TableCell>
                <TableCell align="right">Up/Down</TableCell>
                <TableCell align="right">Connection type</TableCell>
                <TableCell align="right">Delete</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {connections.map(item => (
                <TableRow key={item.node_id}>
                  <TableCell component="th" scope="row">{item.node_id.substring(0, 10)}...</TableCell>
                  <TableCell align="right">{item.peer_host}</TableCell>
                  <TableCell align="right">{item.peer_port}/{item.peer_server_port}</TableCell>
                  <TableCell align="right">{unix_to_short_date(parseInt(item.creation_time))}</TableCell>
                  <TableCell align="right">{unix_to_short_date(parseInt(item.last_message_time))}</TableCell>
                  <TableCell align="right">{Math.floor(item.bytes_written / 1024)}/{Math.floor(item.bytes_read / 1024)} KB</TableCell>
                  <TableCell align="right">{service_connection_types[item.type]}</TableCell>
                  <TableCell className={classes.clickable} onClick={deleteConnection(item.node_id)} align="right"><DeleteForeverIcon></DeleteForeverIcon></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        <h4>Connect to Harvesters</h4>
        <form className={classes.form} noValidate autoComplete="off">
          <TextField label="Ip address / host" value={host} onChange={handleChangeHost}/>
          <TextField label="Port" value={port} onChange={handleChangePort} />
          <Button
            variant="contained"
            color="primary"
            onClick={connectToPeer}
            className={classes.button}
            startIcon={<SettingsInputAntennaIcon />}
          >
            Connect
          </Button>
        </form>
        {connection_error === "" ? "" : <p className={classes.error}>{connection_error}</p>}
        </Grid>
      </Grid>
    </Paper>
  );
};
const Challenges = props => {
  const classes = useStyles();
  const latest_challenges = useSelector(
    state => state.farming_state.farmer.latest_challenges
  );
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
          <Table className={classes.table} size="small" aria-label="a dense table">
            <TableHead>
              <TableRow>
                <TableCell>Challange hash</TableCell>
                <TableCell align="right">Height</TableCell>
                <TableCell align="right">Number of proofs</TableCell>
                <TableCell align="right">Best estimate</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {latest_challenges.map(item => (
                <TableRow key={item.challenge}>
                  <TableCell component="th" scope="row">{item.challenge.substring(0, 10)}...</TableCell>
                  <TableCell align="right">{item.height}</TableCell>
                  <TableCell align="right">{item.estimates.length}</TableCell>
                  <TableCell align="right">{Math.floor(Math.min.apply(Math, item.estimates) / 60)} minutes</TableCell>
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

const Plots = props => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const plots = useSelector(
    state => state.farming_state.harvester.plots
  );
  plots.sort((a, b) => b.size - a.size)
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
    }
  }

  const refreshPlotsClick = () => {
    dispatch(refreshPlots());
  }

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
          <Table className={classes.table} size="small" aria-label="a dense table">
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
              {plots.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage).map(item => (
                <TableRow key={item.filename}>
                  <TableCell component="th" scope="row">{item.filename.substring(0, 60)}...</TableCell>
                  <TableCell align="right">{item.size}</TableCell>
                  <TableCell align="right">{item["plot-seed"].substring(0, 10)}</TableCell>
                  <TableCell align="right">{item.plot_pk.substring(0, 10)}...</TableCell>
                  <TableCell align="right">{item.pool_pk.substring(0, 10)}...</TableCell>
                  <TableCell className={classes.clickable} onClick={deletePlotClick(item.filename)} align="right"><DeleteForeverIcon fontSize="small"></DeleteForeverIcon></TableCell>
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
        </Grid>
      </Grid>
    </Paper>
  );
};

const Farmer = () => {
  const classes = useStyles();
  const [value, setValue] = React.useState(0);

  const handleChange = (event, newValue) => {
    setValue(newValue);
  };


  return (
    <div className={classes.root}>
      <CssBaseline />
      <main className={classes.content}>
        <Paper square className={classes.tabs}>
          <Tabs
            value={value}
            onChange={handleChange}
            // variant="fullWidth"
            centered
            indicatorColor="secondary"
            textColor="secondary"
            aria-label="icon label tabs example"
          >
            <Tab icon={<DonutLargeIcon />} label="Farmer and Harverster" />
            <Tab icon={<HourglassEmptyIcon />} label="Plotting" />
          </Tabs>
          { value === 0 ?
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
                <Connections></Connections>
              </Grid>
              <Grid item xs={12}>
                <Plots></Plots>
              </Grid>
            </Grid>
          </Container> :
          <Container maxWidth="lg" className={classes.container}>
            <Grid container spacing={3}>
            Here goes the plotter
            </Grid>
          </Container>
        }
      </Paper>
      </main>
    </div>
  );
};

export default withRouter(connect()(Farmer));
