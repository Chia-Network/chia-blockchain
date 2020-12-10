import React from 'react';
import { useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Card, Table } from '@chia/core';
import { Typography } from '@material-ui/core';
import type { RootState } from '../../modules/rootReducer';
import PlotAction from './PlotAction';
import type Plot from '../../types/Plot';

const cols = [{
  field: 'filename',
  tooltip: 'filename',
  title: <Trans id="PlotsNotFound.filename">Filename</Trans>,
}, {
  width: '150px',
  field: (plot: Plot) => <PlotAction plot={plot} />,
  title: <Trans id="PlotsNotFound.action">Action</Trans>,
}];

export default function PlotsNotFound() {
  const filenames = useSelector(
    (state: RootState) => state.farming_state.harvester.not_found_filenames,
  );

  if (!filenames || !filenames.length) {
    return null;
  }

  const filenameObjects = filenames.map((filename) => ({
    filename,
  }));

  return (
    <Card
      title={<Trans id="PlotsNotFound.title">Not found Plots</Trans>}
    >
      <Typography component="h6" variant="body2">
        <Trans id="PlotsNotFound.description">
          Caution, deleting these plots will delete them forever. Check
          that the storage devices are properly connected.
        </Trans>
      </Typography>

      <Table cols={cols} rows={filenameObjects} pages />
    </Card>
  );
}
