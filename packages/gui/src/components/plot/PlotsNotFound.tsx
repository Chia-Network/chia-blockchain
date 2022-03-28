import React from 'react';
import { Trans } from '@lingui/macro';
import { Card, Table } from '@chia/core';
import { Typography } from '@mui/material';
import { useGetCombinedNotFoundFilenamesQuery } from '@chia/api-react';
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

export default function PlotsNotFound() {
  const { data: filenames, isLoading } = useGetCombinedNotFoundFilenamesQuery();

  if (!filenames || !filenames.length) {
    return null;
  }

  const filenameObjects = filenames.map((filename) => ({
    filename,
  }));

  return (
    <Card title={<Trans>Not found Plots</Trans>}>
      <Typography component="h6" variant="body2">
        <Trans>
          Caution, deleting these plots will delete them forever. Check that the
          storage devices are properly connected.
        </Trans>
      </Typography>

      <Table cols={cols} rows={filenameObjects} pages />
    </Card>
  );
}
