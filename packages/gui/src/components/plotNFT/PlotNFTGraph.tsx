import React, { ReactNode } from 'react';
import { t } from '@lingui/macro';
import {
  VictoryChart,
  VictoryAxis,
  VictoryArea,
  VictoryTooltip,
  VictoryVoronoiContainer,
} from 'victory';
import { useMeasure } from 'react-use';
import { Box, Typography } from '@mui/material';
import { Flex } from '@chia/core';

const HOUR_SECONDS = 60 * 60;

function aggregatePoints(points, hours = 2, totalHours = 24) {
  const current = Date.now() / 1000;

  const items = [];

  for (let i = -totalHours; i < 0; i += hours) {
    const start = current + i * HOUR_SECONDS;
    const end = current + (i + hours) * HOUR_SECONDS;

    const item = {
      start,
      end,
      x: -i,
      y: 0,
    };

    points.forEach((pointItem) => {
      const [timestamp, pointValue] = pointItem;

      if (timestamp > start && timestamp <= end) {
        item.y += pointValue;
      }
    });

    items.push(item);
  }

  return items;
}

function LinearGradient() {
  return (
    <linearGradient id="graph-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stopColor="rgba(92, 170, 98, 40%)" />
      <stop offset="100%" stopColor="rgba(92, 170, 98, 0%)" />
    </linearGradient>
  );
}

export type PlotNFTGraphProps = {
  title?: ReactNode;
  points: [number, number][];
};

export default function PlotNFTGraph(props: PlotNFTGraphProps) {
  const { points, title } = props;
  const aggregated = aggregatePoints(points, 2);
  const [ref, containerSize] = useMeasure();

  const data = aggregated.map((item) => ({
    x: item.x,
    y: item.y,
    tooltip: t`${item.y} points ${item.x - 2} - ${item.x} hours ago`,
  }));

  const min = aggregated.length
    ? Math.min(...aggregated.map((item) => item.y))
    : 0;
  const max = Math.max(min, ...aggregated.map((item) => item.y));

  return (
    <Box>
      <Flex flexDirection="column" gap={1}>
        {title && (
          <Typography variant="body1" color="textSecondary">
            {title}
          </Typography>
        )}
        <Box height={100} position="relative" ref={ref}>
          <VictoryChart
            animate={{ duration: 300, onLoad: { duration: 0 } }}
            width={containerSize.width || 1}
            height={containerSize.height || 1}
            domain={{ y: [0, max] }}
            padding={0}
            domainPadding={{ x: 0, y: 1 }}
            containerComponent={<VictoryVoronoiContainer />}
          >
            <VictoryArea
              data={data}
              interpolation={'basis'}
              style={{
                data: {
                  stroke: '#5DAA62',
                  strokeWidth: 2,
                  strokeLinecap: 'round',
                  fill: 'url(#graph-gradient)',
                },
              }}
              labels={({ datum }) => datum.tooltip}
              labelComponent={<VictoryTooltip style={{ fontSize: 10 }} />}
            />
            <VictoryAxis
              style={{
                axis: { stroke: 'transparent' },
                ticks: { stroke: 'transparent' },
                tickLabels: { fill: 'transparent' },
              }}
            />
            <LinearGradient />
          </VictoryChart>
        </Box>
      </Flex>
    </Box>
  );
}
