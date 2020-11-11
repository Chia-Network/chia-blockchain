import React, { useMemo } from 'react';
import { sumBy } from 'lodash';
import Grid from '@material-ui/core/Grid';
import { Trans } from '@lingui/macro';
import { Block, Flex, Table } from '@chia/core';
import { useSelector, useDispatch } from 'react-redux';
import Typography from '@material-ui/core/Typography';
import {
  Paper,
  TableRow,
  List,
  ListItem,
  ListItemText,
  Tooltip,
} from '@material-ui/core';
import Button from '@material-ui/core/Button';
import DeleteForeverIcon from '@material-ui/icons/DeleteForever';
import ListItemSecondaryAction from '@material-ui/core/ListItemSecondaryAction';
import IconButton from '@material-ui/core/IconButton';
import Dialog from '@material-ui/core/Dialog';
import DialogActions from '@material-ui/core/DialogActions';
import DialogContent from '@material-ui/core/DialogContent';
import DialogContentText from '@material-ui/core/DialogContentText';
import DialogTitle from '@material-ui/core/DialogTitle';
import TablePagination from '@material-ui/core/TablePagination';
import RefreshIcon from '@material-ui/icons/Refresh';
import {
  refreshPlots,
  deletePlot,
  getPlotDirectories,
} from '../../../modules/harvesterMessages';
import { RootState } from '../../../modules/rootReducer';
import type Plot from '../../../types/Plot';
import { FormatBytes } from '@chia/core';
import plotSizes from '../../../constants/plotSizes';
import PlotStatus from '../PlotStatus';

const cols = [{
  field: ({ file_size, size }: Plot) => {
    const plotSize = plotSizes.filter(item => item.value === size);
    return (
      <>
        {`K-${size}, `}
        <FormatBytes value={file_size} />
      </>
    );
  },
  title: <Trans id="PlotOverviewPlots.size">K-Size</Trans>,
}, {
  field: 'local_sk',
  tooltip: 'local_sk',
  title: <Trans id="PlotOverviewPlots.plotName">Plot Name</Trans>,
}, {
  field: 'farmer_public_key',
  tooltip: 'farmer_public_key',
  title: <Trans id="PlotOverviewPlots.harversterId">Harvester ID</Trans>,
}, {
  field: 'plot-seed',
  tooltip: 'plot-seed',
  title: <Trans id="PlotOverviewPlots.plotSeed">Plot Seed</Trans>,
}, {
  field: 'plot_public_key',
  tooltip: 'plot_public_key',
  title: <Trans id="PlotOverviewPlots.plotKey">Plot Key</Trans>,
}, {
  field: 'pool_public_key',
  tooltip: 'pool_public_key',
  title: <Trans id="PlotOverviewPlots.poolKey">Pool Key</Trans>,
}, {
  field: (plot: Plot) => <PlotStatus plot={plot} />,
  title: <Trans id="PlotOverviewPlots.status">Status</Trans>,
}];

export default function PlotOverviewPlots() {
  const dispatch = useDispatch();
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots ?? [],
  );
  const notFoundFilenames = useSelector(
    (state: RootState) => state.farming_state.harvester.not_found_filenames,
  );
  const failedToOpenFilenames = useSelector(
    (state: RootState) =>
      state.farming_state.harvester.failed_to_open_filenames,
  );

  const sortedPlots = useMemo(() => {
    return [...plots].sort((a, b) => b.size - a.size);
  }, [plots]);

  const totalPlotsSize = useMemo(() => {
    return sumBy(plots, (plot) => plot.file_size);
  }, [plots]);

  const [page, setPage] = React.useState(0);
  const [rowsPerPage, setRowsPerPage] = React.useState(10);
  const [addDirectoryOpen, addDirectorySetOpen] = React.useState(false);
  const [deletePlotName, deletePlotSetName] = React.useState('');
  const [deletePlotOpen, deletePlotSetOpen] = React.useState(false);

  const handleChangePage = (
    event: React.MouseEvent<HTMLButtonElement, MouseEvent> | null,
    newPage: number,
  ) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (
    event: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>,
  ) => {
    setRowsPerPage(+event.target.value);
    setPage(0);
  };

  const refreshPlotsClick = () => {
    dispatch(refreshPlots());
  };
  const addDirectoryHandleClose = () => {
    addDirectorySetOpen(false);
  };

  const handleCloseDeletePlot = () => {
    deletePlotSetOpen(false);
  };

  const handleCloseDeletePlotYes = () => {
    handleCloseDeletePlot();
    dispatch(deletePlot(deletePlotName));
  };

  return (
    <Block>
      <Flex flexDirection="column" gap={2}>
        <Typography variant="h5">
          <Trans id="PlotOverviewPlots.title">
            Local Harvester Plots
          </Trans>
        </Typography>

        <Flex gap={2}>
          <Flex flexGrow={1}>
            <Typography variant="body2">
              <Trans id="PlotOverviewPlots.description">
                Want to earn more Chia? Add more plots to your farm.
              </Trans>
            </Typography>
          </Flex>

          <Typography variant="body2">
            <Trans id="PlotOverviewPlots.description">
              Total Plot Size:
            </Trans>
            {' '}
            <strong>
              <FormatBytes value={totalPlotsSize} precision={3} />
            </strong>
          </Typography>
        </Flex>

        <Table cols={cols} rows={sortedPlots}>
          {}
        </Table>
      </Flex>
    </Block>
  );
}

 /**
    <Paper>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div>
            <Typography component="h6" variant="h6">
              <Trans id="Plots.title">Plots</Trans>
              <Button
                variant="contained"
                color="primary"
                onClick={refreshPlotsClick}
                startIcon={<RefreshIcon />}
              >
                <Trans id="Plots.refreshPlots">Refresh plots</Trans>
              </Button>
              <Button
                variant="contained"
                color="primary"
                onClick={() => {
                  dispatch(getPlotDirectories());
                  addDirectorySetOpen(true);
                }}
              >
                <Trans id="Plots.managePlotDirectories">
                  Manage plot directories
                </Trans>
              </Button>
              <AddPlotDialog
                id="ringtone-menu"
                keepMounted
                open={addDirectoryOpen}
                onClose={addDirectoryHandleClose}
              />
            </Typography>
          </div>

          <TableContainer component={Paper}>
            <Table
              size="small"
              aria-label="a dense table"
            >
              <TableHead>
                <TableRow>
                  <TableCell>
                    <Trans id="Plots.filename">Filename</Trans>
                  </TableCell>
                  <TableCell align="right">
                    <Trans id="Plots.size">Size</Trans>
                  </TableCell>
                  <TableCell align="right">
                    <Trans id="Plots.plotId">Plot id</Trans>
                  </TableCell>
                  <TableCell align="right">
                    <Trans id="Plots.plotPk">Plot pk</Trans>
                  </TableCell>
                  <TableCell align="right">
                    <Trans id="Plots.poolPk">Pool pk</Trans>
                  </TableCell>
                  <TableCell align="right">
                    <Trans id="Plots.delete">Delete</Trans>
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {!!plots &&
                  plots
                    .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
                    .map((item: Plot) => (
                      <TableRow key={item.filename}>
                        <TableCell component="th" scope="row">
                          <Tooltip title={item.filename} interactive>
                            <span>{item.filename.slice(0, 40)}...</span>
                          </Tooltip>
                        </TableCell>
                        <TableCell align="right">
                          {item.size} (
                          {Math.round(
                            (item.file_size * 1000) / (1024 * 1024 * 1024),
                          ) / 1000}
                          GiB)
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip title={item['plot-seed']} interactive>
                            <span>{item['plot-seed'].slice(0, 10)}</span>
                          </Tooltip>
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip title={item.plot_public_key} interactive>
                            <span>{item.plot_public_key.slice(0, 10)}...</span>
                          </Tooltip>
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip title={item.pool_public_key} interactive>
                            <span>{item.pool_public_key.slice(0, 10)}...</span>
                          </Tooltip>
                        </TableCell>
                        <TableCell
                          onClick={() => {
                            deletePlotSetName(item.filename);
                            deletePlotSetOpen(true);
                          }}
                          align="right"
                        >
                          <DeleteForeverIcon fontSize="small" />
                        </TableCell>
                      </TableRow>
                    ))}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            rowsPerPageOptions={[10, 25, 100]}
            component="div"
            count={plots?.length ?? 0}
            rowsPerPage={rowsPerPage}
            page={page}
            onChangePage={handleChangePage}
            onChangeRowsPerPage={handleChangeRowsPerPage}
          />

          {not_found_filenames && not_found_filenames.length > 0 ? (
            <span>
              <div>
                <Typography component="h6" variant="h6">
                  <Trans id="Plots.notFoundPlots">Not found plots</Trans>
                </Typography>
              </div>
              <p>
                <Trans id="Plots.deletePlotsDescription">
                  Caution, deleting these plots will delete them forever. Check
                  that the storage devices are properly connected.
                </Trans>
              </p>
              <List>
                {not_found_filenames.map((filename: string) => (
                  <ListItem key={filename}>
                    <ListItemText primary={filename} />
                    <ListItemSecondaryAction>
                      <IconButton
                        edge="end"
                        aria-label="delete"
                        onClick={() => {
                          deletePlotSetName(filename);
                          deletePlotSetOpen(true);
                        }}
                      >
                        <DeleteForeverIcon />
                      </IconButton>
                    </ListItemSecondaryAction>
                  </ListItem>
                ))}
              </List>{' '}
            </span>
          ) : (
            ''
          )}
          {!!failed_to_open_filenames && failed_to_open_filenames.length > 0 ? (
            <span>
              <div>
                <Typography component="h6" variant="h6">
                  <Trans id="Plots.failedToOpenPlots">
                    Failed to open (invalid plots)
                  </Trans>
                </Typography>
              </div>
              <p>
                <Trans id="Plots.failedToOpenPlotsDescription">
                  These plots are invalid, you might want to delete them
                  forever.
                </Trans>
              </p>
              <List>
                {!!failed_to_open_filenames &&
                  failed_to_open_filenames.map((filename: string) => (
                    <ListItem key={filename}>
                      <ListItemText primary={filename} />
                      <ListItemSecondaryAction>
                        <IconButton
                          edge="end"
                          aria-label="delete"
                          onClick={() => {
                            deletePlotSetName(filename);
                            deletePlotSetOpen(true);
                          }}
                        >
                          <DeleteForeverIcon />
                        </IconButton>
                      </ListItemSecondaryAction>
                    </ListItem>
                  ))}
              </List>
            </span>
          ) : (
            ''
          )}
        </Grid>
      </Grid>
      <Dialog
        open={deletePlotOpen}
        onClose={handleCloseDeletePlot}
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
      >
        <DialogTitle id="alert-dialog-title">
          <Trans id="Plots.deleteAllKeys">Delete all keys</Trans>
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            <Trans id="Plots.deleteAllKeysDescription">
              Are you sure you want to delete the plot? The plot cannot be
              recovered.
            </Trans>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDeletePlot} color="secondary">
            <Trans id="Plots.back">Back</Trans>
          </Button>
          <Button
            onClick={handleCloseDeletePlotYes}
            color="secondary"
            autoFocus
          >
            <Trans id="Plots.delete">Delete</Trans>
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
     */
