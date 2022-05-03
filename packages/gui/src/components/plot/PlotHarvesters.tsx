import React, { useMemo } from 'react';
import { orderBy } from 'lodash';
import { useGetHarvestersSummaryQuery } from '@chia/api-react';
import { Trans } from '@lingui/macro';
import { Loading, Flex } from '@chia/core';
import { Typography } from '@mui/material';
import PlotHarvester from './PlotHarvester';
import isLocalhost from '../../util/isLocalhost';

function getIpAddress(harvester) {
  if (isLocalhost(harvester.connection.host)) {
    return '';
  }

  return harvester.connection.host;
}

export default function PlotHarvesters() {
  const { isLoading, data } = useGetHarvestersSummaryQuery();

  const sortedData = useMemo(() => {
    if (!data) {
      return data;
    }

    return orderBy(data, [getIpAddress], ['asc']);
  }, [data]);

  if (isLoading) {
    return (
      <Loading center />
    );
  }

  return (

    <Flex flexDirection="column" gap={1}>
      <Typography variant="h6">
        <Trans>Harvesters</Trans>
      </Typography>
      <Flex flexDirection="column" gap={3}>
        {sortedData?.map((harvester) => (
          <PlotHarvester
            nodeId={harvester.connection.nodeId}
            key={harvester.connection.nodeId}
            host={harvester.connection.host}
            port={harvester.connection.port}
            expanded={sortedData?.length === 1}
          />
        ))}
      </Flex>
    </Flex>
  );
}
