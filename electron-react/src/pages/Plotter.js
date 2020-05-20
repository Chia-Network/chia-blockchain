import React from "react";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import { withRouter } from "react-router-dom";
import { connect, useSelector, useDispatch } from "react-redux";
import Typography from "@material-ui/core/Typography";
import Box from "@material-ui/core/Box";
import {
  Paper,
  FormControl,
  InputLabel,
  Select,
  MenuItem
} from "@material-ui/core";
import Button from "@material-ui/core/Button";
import TextField from "@material-ui/core/TextField";

import { openDialog } from "../modules/dialogReducer";
import isElectron from "is-electron";
import {
  workspaceSelected,
  finalSelected,
  startPlotting,
  resetProgress
} from "../modules/plotter_messages";
import { stopService } from "../modules/daemon_messages";
import { service_plotter } from "../util/service_names";
const drawerWidth = 180;

const useStyles = makeStyles(theme => ({
  root: {
    display: "flex",
    paddingLeft: "0px"
  },
  tabs: {
    flexGrow: 1
  },
  form: {
    margin: theme.spacing(1)
  },
  clickable: {
    cursor: "pointer"
  },
  error: {
    color: "red"
  },
  refreshButton: {
    marginLeft: "20px"
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
    marginTop: theme.spacing(3),
    paddingBottom: theme.spacing(6),
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
    marginTop: theme.spacing(2),
    marginLeft: theme.spacing(2),
    marginRight: theme.spacing(2)
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
    minWidth: 650
  },
  selectButton: {
    width: 80,
    paddingLeft: theme.spacing(2),
    height: 56
  },
  input: {
    paddingRight: theme.spacing(2)
  },
  createButton: {
    float: "right",
    width: 150,
    paddingLeft: theme.spacing(2),
    height: 56,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(2)
  },
  logContainer: {
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    minHeight: 400,
    maxHeight: 400,
    maxWidth: "100%",
    backgroundColor: "#bbbbbb",
    whiteSpace: "pre-wrap",
    paddingTop: theme.spacing(1),
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingBottom: theme.spacing(3),
    overflowY: "auto",
    overflowWrap: "break-word",
    lineHeight: 1.8
  },
  logPaper: {
    maxWidth: "100%",
    marginBottom: theme.spacing(3),
    marginTop: theme.spacing(3)
  },
  cancelButton: {
    float: "right",
    width: 150,
    paddingLeft: theme.spacing(2),
    height: 56,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(2)
  },
  clearButton: {
    float: "right",
    width: 150,
    marginRight: theme.spacing(2),
    height: 56,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(2)
  }
}));

const plot_size_options = [
  //{ label: "60MB", value: 16, workspace: "3.5GB" },
  { label: "600MB", value: 25, workspace: "3.5GB" },
  { label: "1.3GB", value: 26, workspace: "7GB" },
  { label: "2.7GB", value: 27, workspace: "14.5GB" },
  { label: "5.6GB", value: 28, workspace: "30.3GB" },
  { label: "11.5GB", value: 29, workspace: "61GB" },
  { label: "23.8GB", value: 30, workspace: "128GB" },
  { label: "49.1GB", value: 31, workspace: "262GB" },
  { label: "101.4GB", value: 32, workspace: "566GB" },
  { label: "208.8GB", value: 33, workspace: "1095GB" },
  { label: "429.8GB", value: 34, workspace: "2287GB" },
  { label: "884.1GB", value: 35, workspace: "4672GB" }
];

const WorkLocation = () => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const work_location = useSelector(
    state => state.plot_control.workspace_location
  );
  async function select() {
    if (isElectron()) {
      const dialogOptions = { properties: ["openDirectory"] };
      const result = await window.remote.dialog.showOpenDialog(dialogOptions);
      const filePath = result["filePaths"][0];
      dispatch(workspaceSelected(filePath));
    } else {
      dispatch(
        openDialog("", "This feature is available only from electron app")
      );
    }
  }

  return (
    <Grid item xs={12}>
      <div className={classes.cardSubSection}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              disabled
              className={classes.input}
              fullWidth
              label={work_location === "" ? "Work Location" : work_location}
              variant="outlined"
            />
          </Box>
          <Box>
            <Button
              onClick={select}
              className={classes.selectButton}
              variant="contained"
              color="primary"
            >
              Select
            </Button>
          </Box>
        </Box>
      </div>
    </Grid>
  );
};

const FinalLocation = () => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const final_location = useSelector(
    state => state.plot_control.final_location
  );
  async function select() {
    if (isElectron()) {
      const dialogOptions = { properties: ["openDirectory"] };
      const result = await window.remote.dialog.showOpenDialog(dialogOptions);
      const filePath = result["filePaths"][0];
      dispatch(finalSelected(filePath));
    } else {
      dispatch(
        openDialog("", "This feature is available only from electron app")
      );
    }
  }

  return (
    <Grid item xs={12}>
      <div className={classes.cardSubSection}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              disabled
              className={classes.input}
              fullWidth
              label={final_location === "" ? "Final Location" : final_location}
              variant="outlined"
            />
          </Box>
          <Box>
            <Button
              onClick={select}
              className={classes.selectButton}
              variant="contained"
              color="primary"
            >
              Select
            </Button>
          </Box>
        </Box>
      </div>
    </Grid>
  );
};

const CreatePlot = () => {
  const dispatch = useDispatch();
  const classes = useStyles();
  const work_location = useSelector(
    state => state.plot_control.workspace_location
  );
  const final_location = useSelector(
    state => state.plot_control.final_location
  );
  var plot_size_ref = null;
  var plot_count_ref = null;

  function create() {
    const N = plot_count_ref.value;
    const K = plot_size_ref.value;
    console.log(work_location);
    console.log(final_location);
    console.log("N: " + N);
    console.log("K: " + K);
    dispatch(startPlotting(K, N, work_location, final_location));
  }

  var plot_count_options = [];
  for (var i = 1; i < 10; i++) {
    plot_count_options.push(i);
  }

  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Create Plot
            </Typography>
          </div>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Grid container spacing={2}>
              <Grid item xs={6}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>Plot Size</InputLabel>
                  <Select
                    value={25}
                    inputRef={input => {
                      plot_size_ref = input;
                    }}
                    label="Plot Size"
                  >
                    {plot_size_options.map(option => (
                      <MenuItem
                        value={option.value}
                        key={"size" + option.value}
                      >
                        {option.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={6}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>Plot Count</InputLabel>
                  <Select
                    value={1}
                    inputRef={input => {
                      plot_count_ref = input;
                    }}
                    label="Colour"
                  >
                    {plot_count_options.map(option => (
                      <MenuItem value={option} key={"count" + option}>
                        {option}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
          </div>
        </Grid>
        <WorkLocation></WorkLocation>
        <FinalLocation></FinalLocation>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Grid container spacing={2}>
              <Grid item xs={12}>
                <Button
                  onClick={create}
                  className={classes.createButton}
                  variant="contained"
                  color="primary"
                >
                  Create
                </Button>
              </Grid>
            </Grid>
          </div>
        </Grid>
      </Grid>
    </Paper>
  );
};

const Proggress = () => {
  const progress = useSelector(state => state.plot_control.progress);
  const classes = useStyles();
  const dispatch = useDispatch();
  function clearLog() {
    dispatch(resetProgress());
  }
  function cancel() {
    dispatch(stopService(service_plotter));
  }
  return (
    <div>
      <Paper className={classes.balancePaper}>
        <div className={classes.cardTitle}>
          <Typography component="h6" variant="h6">
            Progress
          </Typography>
        </div>
        <div className={classes.logPaper}>
          <div className={classes.logContainer}>{progress}</div>
        </div>
        <div className={classes.cardSubSection}>
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <Button
                onClick={cancel}
                className={classes.cancelButton}
                variant="contained"
                color="primary"
              >
                Cancel
              </Button>
              <Button
                onClick={clearLog}
                className={classes.clearButton}
                variant="contained"
                color="primary"
              >
                Clear Log
              </Button>
            </Grid>
          </Grid>
        </div>
      </Paper>
    </div>
  );
};

const Plotter = () => {
  const in_progress = useSelector(
    state => state.plot_control.plotting_in_proggress
  );
  return (
    <div>
      <CreatePlot></CreatePlot>
      {in_progress ? <Proggress></Proggress> : <div></div>}
    </div>
  );
};

export default withRouter(connect()(Plotter));
