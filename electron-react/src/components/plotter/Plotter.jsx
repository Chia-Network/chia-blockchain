import React from 'react';
import Grid from '@material-ui/core/Grid';
import { makeStyles } from '@material-ui/core/styles';
import { Trans } from '@lingui/macro';
import { useSelector, useDispatch } from 'react-redux';
import Typography from '@material-ui/core/Typography';
import Box from '@material-ui/core/Box';
import {
  Paper,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@material-ui/core';
import Button from '@material-ui/core/Button';
import TextField from '@material-ui/core/TextField';
import InputAdornment from '@material-ui/core/InputAdornment';
import FormHelperText from '@material-ui/core/FormHelperText';
import isElectron from 'is-electron';
import Input from '@material-ui/core/Input';
import { openDialog } from '../../modules/dialog';
import {
  workspaceSelected,
  finalSelected,
  startPlotting,
  resetProgress,
} from '../../modules/plotter_messages';
import { stopService } from '../../modules/daemon_messages';
import { service_plotter } from '../../util/service_names';
import DashboardTitle from '../dashboard/DashboardTitle';

const drawerWidth = 180;

const useStyles = makeStyles((theme) => ({
  root: {
    display: 'flex',
    paddingLeft: '0px',
  },
  tabs: {
    flexGrow: 1,
  },
  form: {
    margin: theme.spacing(1),
  },
  clickable: {
    cursor: 'pointer',
  },
  error: {
    color: 'red',
  },
  refreshButton: {
    marginLeft: '20px',
  },
  menuButton: {
    marginRight: 36,
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
    marginTop: theme.spacing(3),
    paddingBottom: theme.spacing(6),
    height: 'calc(100vh - 64px)',
    overflowX: 'hidden',
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
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
    marginTop: theme.spacing(2),
    marginLeft: theme.spacing(2),
    marginRight: theme.spacing(2),
  },
  bottomOptions: {
    position: 'absolute',
    bottom: 0,
    width: '100%',
  },
  cardTitle: {
    paddingLeft: theme.spacing(3),
    paddingTop: theme.spacing(2),
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
  selectButton: {
    width: 80,
    paddingLeft: theme.spacing(2),
    height: 56,
  },
  input: {
    paddingRight: theme.spacing(2),
    cursor: 'pointer',
  },
  createButton: {
    float: 'right',
    width: 150,
    paddingLeft: theme.spacing(2),
    height: 56,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(2),
    background: 'linear-gradient(45deg, #0a6b19 30%, #6ff196 90%)',
    boxShadow: '0 3px 5px 2px rgba(255, 105, 135, .3)',
    color: 'white',
  },
  logContainer: {
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    minHeight: 400,
    maxHeight: 400,
    maxWidth: '100%',
    backgroundColor: '#f1f1f1',
    border: '1px solid #888888',
    whiteSpace: 'pre-wrap',
    paddingTop: theme.spacing(1),
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingBottom: theme.spacing(3),
    overflowY: 'auto',
    overflowWrap: 'break-word',
    lineHeight: 1.8,
  },
  logPaper: {
    maxWidth: '100%',
    marginBottom: theme.spacing(3),
    marginTop: theme.spacing(3),
  },
  cancelButton: {
    float: 'right',
    width: 150,
    paddingLeft: theme.spacing(2),
    height: 56,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(2),
  },
  clearButton: {
    float: 'right',
    width: 150,
    marginRight: theme.spacing(2),
    height: 56,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(2),
  },
}));

const plot_size_options = [
  { label: '600MiB', value: 25, workspace: '1.8GiB', default_ram: 200 },
  { label: '1.3GiB', value: 26, workspace: '3.6GiB', default_ram: 200 },
  { label: '2.7GiB', value: 27, workspace: '9.2GiB', default_ram: 200 },
  { label: '5.6GiB', value: 28, workspace: '19GiB', default_ram: 200 },
  { label: '11.5GiB', value: 29, workspace: '38GiB', default_ram: 500 },
  { label: '23.8GiB', value: 30, workspace: '83GiB', default_ram: 1000 },
  { label: '49.1GiB', value: 31, workspace: '165GiB', default_ram: 2000 },
  { label: '101.4GiB', value: 32, workspace: '331GiB', default_ram: 3072 },
  { label: '208.8GiB', value: 33, workspace: '660GiB', default_ram: 6000 },
  // workspace are guesses using 55.35% - rounded up - past here
  { label: '429.8GiB', value: 34, workspace: '1300GiB', default_ram: 12000 },
  { label: '884.1GiB', value: 35, workspace: '2600GiB', default_ram: 24000 },
];

const WorkLocation = () => {
  const classes = useStyles();
  const dispatch = useDispatch();
  const work_location = useSelector(
    (state) => state.plot_control.workspace_location,
  );
  async function select() {
    if (isElectron()) {
      const dialogOptions = {
        properties: ['openDirectory', 'showHiddenFiles'],
      };
      const result = await window.remote.dialog.showOpenDialog(dialogOptions);
      const filePath = result.filePaths[0];
      if (filePath) {
        dispatch(workspaceSelected(filePath));
      }
    } else {
      dispatch(
        openDialog(
          '',
          <Trans id="PlotterWorkLocation.availableOnlyFromElectron">
            This feature is available only from electron app
          </Trans>,
        ),
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
              variant="outlined"
              className={classes.input}
              fullWidth
              onClick={select}
              label={
                work_location === '' ? (
                  <Trans id="PlotterWorkLocation.temporaryFolderLocation">
                    Temporary folder location
                  </Trans>
                ) : (
                  work_location
                )
              }
            />
          </Box>
          <Box>
            <Button
              onClick={select}
              className={classes.selectButton}
              variant="contained"
              color="primary"
            >
              <Trans id="PlotterWorkLocation.select">Select</Trans>
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
    (state) => state.plot_control.final_location,
  );
  async function select() {
    if (isElectron()) {
      const dialogOptions = {
        properties: ['openDirectory', 'showHiddenFiles'],
      };
      const result = await window.remote.dialog.showOpenDialog(dialogOptions);
      const filePath = result.filePaths[0];
      if (filePath) {
        dispatch(finalSelected(filePath));
      }
    } else {
      dispatch(
        openDialog(
          '',
          <Trans id="PlotterFinalLocation.availableOnlyFromElectron">
            This feature is available only from electron app
          </Trans>,
        ),
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
              onClick={select}
              fullWidth
              label={
                final_location === '' ? (
                  <Trans id="PlotterFinalLocation.finalFolderLocation">
                    Final folder location
                  </Trans>
                ) : (
                  final_location
                )
              }
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
              <Trans id="PlotterFinalLocation.select">Select</Trans>
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
    (state) => state.plot_control.workspace_location,
  );
  let t2 = useSelector((state) => state.plot_control.t2);
  const final_location = useSelector(
    (state) => state.plot_control.final_location,
  );
  const [plotSize, setPlotSize] = React.useState(32);
  const [plotCount, setPlotCount] = React.useState(1);
  const [maxRam, setMaxRam] = React.useState(3072);
  const [numThreads, setNumThreads] = React.useState(2);
  const [numBuckets, setNumBuckets] = React.useState(0);
  const [stripeSize, setStripeSize] = React.useState(65536);

  const changePlotSize = (event) => {
    setPlotSize(event.target.value);
    for (const pso of plot_size_options) {
      if (pso.value === event.target.value) {
        setMaxRam(pso.default_ram);
      }
    }
  };
  const changePlotCount = (event) => {
    setPlotCount(event.target.value);
  };
  const handleSetMaxRam = (event) => {
    setMaxRam(event.target.value);
  };
  const handleSetNumBuckets = (event) => {
    setNumBuckets(event.target.value);
  };
  const handleSetNumThreads = (event) => {
    setNumThreads(event.target.value);
  };
  const handleSetStripeSize = (event) => {
    setStripeSize(event.target.value);
  };

  function create() {
    if (!work_location || !final_location) {
      dispatch(
        openDialog(
          <Trans id="CreatePlot.specifyFinalDirectory">
            Please specify a temporary and final directory
          </Trans>,
        ),
      );
      return;
    }
    const N = plotCount;
    const K = plotSize;
    if (!t2 || t2 === '') {
      t2 = work_location;
    }
    dispatch(
      startPlotting(
        K,
        N,
        work_location,
        t2,
        final_location,
        maxRam,
        numBuckets,
        numThreads,
        stripeSize,
      ),
    );
  }

  const plot_count_options = [];
  for (let i = 1; i < 30; i++) {
    plot_count_options.push(i);
  }

  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              <Trans id="CreatePlot.title">Create Plot</Trans>
            </Typography>
          </div>
        </Grid>
        <Grid className={classes.cardTitle} item xs={12}>
          <p>
            <Trans id="CreatePlot.description">
              Using this tool, you can create plots, which are allocated space
              on your hard drive used to farm and earn Chia. Also, temporary
              files are created during the plotting process, which exceed the
              size of the final plot files, so make sure you have enough space.
              Try to use a fast drive like an SSD for the temporary folder, and
              a large slow hard drive (like external HDD) for the final folder.
            </Trans>
          </p>
        </Grid>
        <Grid item xs={12}>
          <div className={classes.cardSubSection}>
            <Grid container spacing={2}>
              <Grid item xs={4}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>
                    <Trans id="CreatePlot.plotSize">Plot Size</Trans>
                  </InputLabel>
                  <Select
                    value={plotSize}
                    onChange={changePlotSize}
                    label={<Trans id="CreatePlot.plotSize">Plot Size</Trans>}
                  >
                    {plot_size_options.map((option) => (
                      <MenuItem
                        value={option.value}
                        key={`size${option.value}`}
                      >
                        {option.label} (k={option.value}, temporary space:{' '}
                        {option.workspace})
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={4}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel><Trans id="CreatePlot.plotCount">Plot Count</Trans></InputLabel>
                  <Select
                    value={plotCount}
                    onChange={changePlotCount}
                    label={<Trans id="CreatePlot.colour">Colour</Trans>}
                  >
                    {plot_count_options.map((option) => (
                      <MenuItem value={option} key={`count${option}`}>
                        {option}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={4}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>
                    <Trans id="CreatePlot.ramMaxUsage">RAM max usage</Trans>
                  </InputLabel>
                  <Input
                    value={maxRam}
                    endAdornment={
                      <InputAdornment position="end">MiB</InputAdornment>
                    }
                    onChange={handleSetMaxRam}
                    type="number"
                  />
                  <FormHelperText id="standard-weight-helper-text">
                    <Trans id="CreatePlot.ramMaxUsageDescription">
                      More memory slightly increases speed
                    </Trans>
                  </FormHelperText>
                </FormControl>
              </Grid>
            </Grid>
            <Grid container spacing={2}>
              <Grid item xs={4}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>
                    <Trans id="CreatePlot.numberOfThreads">
                      Number of threads
                    </Trans>
                  </InputLabel>
                  <Input
                    value={numThreads}
                    onChange={handleSetNumThreads}
                    type="number"
                  />
                </FormControl>
              </Grid>
              <Grid item xs={4}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>
                    <Trans id="CreatePlot.numberOfBuckets">
                      Number of buckets
                    </Trans>
                  </InputLabel>
                  <Input
                    value={numBuckets}
                    onChange={handleSetNumBuckets}
                    type="number"
                  />
                  <FormHelperText id="standard-weight-helper-text">
                    <Trans id="CreatePlot.numberOfBucketsDescription">
                      0 automatically chooses bucket count
                    </Trans>
                  </FormHelperText>
                </FormControl>
              </Grid>
              <Grid item xs={4}>
                <FormControl
                  fullWidth
                  variant="outlined"
                  className={classes.formControl}
                >
                  <InputLabel>
                    <Trans id="CreatePlot.stripeSize">Stripe Size</Trans>
                  </InputLabel>
                  <Input
                    value={stripeSize}
                    onChange={handleSetStripeSize}
                    type="number"
                  />
                </FormControl>
              </Grid>
            </Grid>
          </div>
        </Grid>
        <WorkLocation />
        <FinalLocation />
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
                  <Trans id="CreatePlot.create">Create</Trans>
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
  const progress = useSelector((state) => state.plot_control.progress);
  const classes = useStyles();
  const dispatch = useDispatch();
  function clearLog() {
    dispatch(resetProgress());
  }
  function cancel() {
    dispatch(stopService(service_plotter));
  }
  const plotting_stopped = useSelector(
    (state) => state.plot_control.plotting_stopped,
  );
  return (
    <div>
      <Paper className={classes.balancePaper}>
        <div className={classes.cardTitle}>
          <Typography component="h6" variant="h6">
            <Trans id="PlotterProgress.title">Progress</Trans>
          </Typography>
        </div>
        <div className={classes.logPaper}>
          <Box className={classes.logContainer} fontFamily="Monospace">
            {progress}
          </Box>
        </div>
        <div className={classes.cardSubSection}>
          {plotting_stopped ? (
            <p>
              <Trans id="PlotterProgress.plottingStoppedSuccesfully">
                Plotting stopped succesfully.
              </Trans>
            </p>
          ) : (
            ''
          )}
          <Grid container spacing={2}>
            <Grid item xs={12}>
              {!plotting_stopped ? (
                <Button
                  onClick={cancel}
                  className={classes.cancelButton}
                  variant="contained"
                  color="primary"
                >
                  <Trans id="PlotterProgress.cancel">Cancel</Trans>
                </Button>
              ) : (
                ''
              )}
              <Button
                onClick={clearLog}
                className={classes.clearButton}
                variant="contained"
                color="primary"
              >
                <Trans id="PlotterProgress.clearLog">Clear Log</Trans>
              </Button>
            </Grid>
          </Grid>
        </div>
      </Paper>
    </div>
  );
};

export default function Plotter() {
  const in_progress = useSelector(
    (state) => state.plot_control.plotting_in_proggress,
  );
  const plotting_stopped = useSelector(
    (state) => state.plot_control.plotting_stopped,
  );
  return (
    <div>
      <DashboardTitle>
        <Trans id="Plotter.title">Plot</Trans>
      </DashboardTitle>
      <CreatePlot />
      {in_progress || plotting_stopped ? <Proggress /> : <div />}
    </div>
  );
}
