import React, { useMemo } from 'react';
import { sumBy } from 'lodash';
import { Trans } from '@lingui/macro';
import styled from 'styled-components';
import { Card, Flex, Table, FormatBytes } from '@chia/core';
import { TableCell, TableRow } from '@material-ui/core';
import { useSelector } from 'react-redux';
import Typography from '@material-ui/core/Typography';
import { RootState } from '../../../modules/rootReducer';
import type Plot from '../../../types/Plot';
import PlotStatus from '../PlotStatus';
import PlotAction from '../PlotAction';
import PlotHeader from '../PlotHeader';
import PlotQueueSize from '../queue/PlotQueueSize';
import PlotQueueActions from '../queue/PlotQueueActions';
import PlotQueueIndicator from '../queue/PlotQueueIndicator';

const StyledTableRowQueue = styled(TableRow)`
  background-color: ${({ theme }) => theme.palette.type === 'dark' 
    ? '#1C87FB'
    : '#F6EEDF'};
`;

const cols = [{
  minWidth: '130px',
  field: ({ file_size, size }: Plot) => (
    <>
      {`K-${size}, `}
      <FormatBytes value={file_size} />
    </>
  ),
  title: <Trans id="PlotOverviewPlots.size">K-Size</Trans>,
}, {
  minWidth: '100px',
  field: 'local_sk',
  tooltip: 'local_sk',
  title: <Trans id="PlotOverviewPlots.plotName">Plot Name</Trans>,
}, {
  minWidth: '100px',
  field: 'farmer_public_key',
  tooltip: 'farmer_public_key',
  title: <Trans id="PlotOverviewPlots.harversterId">Harvester ID</Trans>,
}, {
  minWidth: '100px',
  field: 'plot-seed',
  tooltip: 'plot-seed',
  title: <Trans id="PlotOverviewPlots.plotSeed">Plot Seed</Trans>,
}, {
  minWidth: '100px',
  field: 'plot_public_key',
  tooltip: 'plot_public_key',
  title: <Trans id="PlotOverviewPlots.plotKey">Plot Key</Trans>,
}, {
  minWidth: '100px',
  field: 'pool_public_key',
  tooltip: 'pool_public_key',
  title: <Trans id="PlotOverviewPlots.poolKey">Pool Key</Trans>,
}, {
  minWidth: '90px',
  field: (plot: Plot) => <PlotStatus plot={plot} />,
  title: <Trans id="PlotOverviewPlots.status">Status</Trans>,
}, {
  minWidth: '80px',
  field: (plot: Plot) => <PlotAction plot={plot} />,
  title: <Trans id="PlotOverviewPlots.action">Action</Trans>,
}];

export default function PlotOverviewPlots() {
  const plots = useSelector(
    (state: RootState) => state.farming_state.harvester.plots ?? [],
  );

  const sortedPlots = useMemo(() => {
    return [...plots].sort((a, b) => b.size - a.size);
  }, [plots]);

  const totalPlotsSize = useMemo(() => {
    return sumBy(plots, (plot) => plot.file_size);
  }, [plots]);

  const plotQueue = useSelector(
    (state: RootState) => state.plot_queue.queue ?? [],
  );

  return (
    <>
      <PlotHeader />
      <Card
        title={(
          <Trans id="PlotOverviewPlots.title">
            Local Harvester Plots
          </Trans>
        )}
      >
        <Flex gap={1}>
          <Flex flexGrow={1}>
            <Typography variant="body2">
              <Trans id="PlotOverviewPlots.description">
                Want to earn more Chia? Add more plots to your farm.
              </Trans>
            </Typography>
          </Flex>

          <Typography variant="body2">
            <Trans id="PlotOverviewPlots.totalPlotSize">
              Total Plot Size:
            </Trans>
            {' '}
            <strong>
              <FormatBytes value={totalPlotsSize} precision={3} />
            </strong>
          </Typography>
        </Flex>

        <Table cols={cols} rows={sortedPlots} pages>
          {plotQueue.map((item) => {
            const { id } = item;

            return (
              <StyledTableRowQueue key={id}>
                <TableCell>
                  <PlotQueueSize queueItem={item} />
                </TableCell>
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell />
                <TableCell>
                  <PlotQueueIndicator queueItem={item} />
                </TableCell>
                <TableCell>
                  <PlotQueueActions queueItem={item} />
                </TableCell>
              </StyledTableRowQueue>
            );
          })}
        </Table>
      </Card>
    </>
  );
}
