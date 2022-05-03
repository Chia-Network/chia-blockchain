import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useGetThrottlePlotQueueQuery } from '@chia/api-react';
import { TableCell, TableRow } from '@mui/material';
import { Card, Table } from '@chia/core';
import styled from 'styled-components';
import PlotQueueSize from './queue/PlotQueueSize';
import PlotQueueIndicator from './queue/PlotQueueIndicator';
import PlotQueueActions from './queue/PlotQueueActions';

export const StyledTableRow = styled(({ odd, ...rest }) => <TableRow {...rest} />)`
  ${({ odd, theme }) => odd
    ? `background-color: ${theme.palette.action.hover};`
    : undefined
  }
`;

const cols = [
  {
    title: <Trans>K-Size</Trans>,
  },
  {
    title: <Trans>Queue Name</Trans>,
  },
  {
    title: <Trans>Status</Trans>,
  },
  {
    title: <Trans>Action</Trans>,
  },
];

export default function PlotPlotting() {
  const { isLoading, queue } = useGetThrottlePlotQueueQuery();

  const nonFinisged = useMemo(() => {
    return queue?.filter((item) => item.state !== 'FINISHED');
  }, [queue]);

  if (isLoading || !nonFinisged?.length) {
    return null;
  }

  return (
    <Card title={<Trans>Plotting</Trans>} titleVariant="h6" transparent>
      <Table
        cols={cols}
        rows={[]}
      >
        {nonFinisged.map((item, index) => (
          <StyledTableRow key={item.id} odd={index % 2}>
            <TableCell>
              <PlotQueueSize queueItem={item} />
            </TableCell>
            <TableCell>{item.queue}</TableCell>
            <TableCell>
              <PlotQueueIndicator queueItem={item} />
            </TableCell>
            <TableCell>
              <PlotQueueActions queueItem={item} />
            </TableCell>
          </StyledTableRow>
        ))}
      </Table>
    </Card>
  );
}
