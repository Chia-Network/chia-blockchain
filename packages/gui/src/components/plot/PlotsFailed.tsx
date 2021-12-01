import React from 'react';
import { Trans } from '@lingui/macro';
import { Card, Table } from '@chia/core';
import { useGetCombinedFailedToOpenFilenamesQuery } from '@chia/api-react';
import { Typography } from '@material-ui/core';
import PlotAction from './PlotAction';
import type { Plot } from '@chia/api';

const cols = [
  {
    field: 'filename',
    tooltip: 'filename',
    title: <Trans>Filename</Trans>,
  },
  {
    width: '150px',
    field: (plot: Plot) => <PlotAction plot={plot} />,
    title: <Trans>Action</Trans>,
  },
];

export default function PlotsFailed() {
  const { data: filenames, isLoading } = useGetCombinedFailedToOpenFilenamesQuery();

  if (!filenames || !filenames.length) {
    return null;
  }

  const filenameObjects = filenames.map((filename) => ({
    filename,
  }));

  return (
    <Card title={<Trans>Failed to open (invalid plots)</Trans>}>
      <Typography component="h6" variant="body2">
        <Trans>These plots are invalid, you might want to delete them.</Trans>
      </Typography>

      <Table cols={cols} rows={filenameObjects} pages />
    </Card>
  );
}
