import React from 'react';
import { Box, Typography, LinearProgress, type LinearProgressProps } from '@mui/material';
import { useGetHarvesterStats } from '@chia/api-react';

function LinearProgressWithLabel(props: LinearProgressProps & { value: number }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', minWidth: '120px' }}>
      <Box sx={{ width: '100%', mr: 1 }}>
        <LinearProgress variant="determinate" {...props} />
      </Box>
      <Box sx={{ minWidth: 35 }}>
        <Typography variant="caption" color="textSecondary">{`${Math.round(
          props.value,
        )}%`}</Typography>
      </Box>
    </Box>
  );
}

export type PlotHarvesterStateProps = {
  nodeId: string;
};

export default function PlotHarvesterState(props: PlotHarvesterStateProps) {
  const { nodeId } = props;
  const { harvester } = useGetHarvesterStats(nodeId);

  if (harvester?.syncing?.initial !== true) {
    return null;
  }

  const progress = Math.floor(harvester.syncing.plotFilesProcessed / harvester.syncing.plotFilesTotal * 100);

  return (
    <LinearProgressWithLabel value={progress} />
  );
}
