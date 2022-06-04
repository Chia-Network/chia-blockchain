import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useGetThrottlePlotQueueQuery } from '@chia/api-react';
import { TableRow } from '@mui/material';
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
    field: (queueItem) => <PlotQueueSize queueItem={queueItem} />,
  },
  {
    title: <Trans>Queue Name</Trans>,
    field: 'queue',
  },
  {
    title: <Trans>Status</Trans>,
    field: (queueItem) => <PlotQueueIndicator queueItem={queueItem} />,
  },
  {
    title: <Trans>Action</Trans>,
    field: (queueItem) => <PlotQueueActions queueItem={queueItem} />,
  },
];

export default function PlotPlotting() {
  const { isLoading, queue } = useGetThrottlePlotQueueQuery();

  const nonFinished = useMemo(() => {
    return queue?.filter((item) => item.state !== 'FINISHED');
  }, [queue]);

  if (isLoading || !nonFinished?.length) {
    return null;
  }

  return (
    <Card title={<Trans>Plotting</Trans>} titleVariant="h6" transparent>
      <Table
        cols={cols}
        rows={nonFinished}
        isLoading={isLoading}
      />
    </Card>
  );
}
