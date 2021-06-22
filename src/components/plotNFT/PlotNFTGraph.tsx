import React from 'react';
import { linearGradientDef } from '@nivo/core';
import { t } from '@lingui/macro';
import { ResponsiveLine } from '@nivo/line';
import { Typography, Paper } from '@material-ui/core';
import { Flex } from '@chia/core';
import styled from 'styled-components';

const StyledRoot = styled.div`
  // border-radius: 1rem;
  // background-color: #303030;
  // padding: 1rem;
`;

const StyledGraphContainer = styled.div`
  height: 100px;
`;

const StyledTooltip = styled(Paper)`
  padding: 0.25rem 0.5rem;
`;

const HOUR_SECONDS = 60 * 60;

function aggregatePoints(points, hours: number = 2, totalHours: number = 24) {
  let current = Date.now() / 1000;

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

type Props = {
  title?: ReactNode;
  points: [number, number][];
};


export default function PlotNFTGraph(props: Props) {
  const { points, title } = props;
  const aggregated = aggregatePoints(points, 2);

  const data = [{
    id: 'Points',
    data: aggregated.map(item => ({
      x: item.x,
      y: item.y,
      tooltip: t`${item.y} points ${item.x - 2} - ${item.x} hours ago`,
    })),
  }];

  const max = Math.max(...aggregated.map(item => item.y));

  // https://github.com/plouc/nivo/issues/308#issuecomment-451280930
  const theme = {
    tooltip: {
      container: {
        color: 'rgba(0, 0, 0, 0.87)',
      },
    },
  };

  return (
    <StyledRoot>
      <Flex flexDirection="column" gap={1}>
      {title && (
        <Typography variant="body1" color="textSecondary">
          {title}
        </Typography>
      )}
      <StyledGraphContainer>
        <ResponsiveLine
          margin={{ top: 2, bottom: 2 }}
          data={data}
          theme={theme}
          xScale={{ type: 'point' }}
          yScale={{
            type: 'linear',
            stacked: true,
            min: 0,
            max,
          }}
          tooltip={({ point }) => (
            <StyledTooltip>
              {point?.data?.tooltip}
            </StyledTooltip>
          )}
          colors={{ scheme: 'accent' }}
          axisTop={null}
          axisRight={null}
          axisBottom={null}
          axisLeft={null /* {
            tickValues: [0, max],
            tickSize: 0,
            tickPadding: -40,
            tickRotation: 1,
            
            legend: '',
            legendPosition: 'middle'
          } */}
          pointSize={0}
          pointBorderWidth={0}
          useMesh={true}
          curve="monotoneX"
          defs={[
            linearGradientDef('gradientA', [
                { offset: 0, color: 'inherit' },
                { offset: 100, color: 'inherit', opacity: 0 },
            ]),
          ]}
          fill={[{ match: '*', id: 'gradientA' }]}
          areaOpacity={0.3}
          enableGridX={false}
          enableGridY={false}
          enableArea
        />
      </StyledGraphContainer>
      </Flex>
    </StyledRoot>
  );
}