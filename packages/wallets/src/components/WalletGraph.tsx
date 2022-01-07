import React, { ReactNode } from 'react';
import { linearGradientDef } from '@nivo/core';
import { ResponsiveLine } from '@nivo/line';
import { orderBy, groupBy, sumBy, map } from 'lodash';
import { /* Typography, */ Paper } from '@material-ui/core';
import styled from 'styled-components';
import { useGetWalletBalanceQuery } from '@chia/api-react';
import { TransactionType } from '@chia/api';
import type { Transaction } from '@chia/api';
import { mojoToChia, blockHeightToTimestamp } from '@chia/core';
import useWalletTransactions from '../hooks/useWalletTransactions';

/*
const HOUR_SECONDS = 60 * 60;

const StyledRoot = styled.div`
  // border-radius: 1rem;
  // background-color: #303030;
  // padding: 1rem;
`;
*/

const StyledGraphContainer = styled.div`
  position: relative;
  min-height: 100px;
  height: ${({ height }) =>
    typeof height === 'string' ? height : `${height}px`};
`;

const StyledTooltip = styled(Paper)`
  padding: 0.25rem 0.5rem;
  display: none;
`;

/*
const StyledMaxTypography = styled(Typography)`
  position: absolute;
  left: 0;
  top: 0.1rem;
  font-size: 0.625rem;
`;

const StyledMinTypography = styled(Typography)`
  position: absolute;
  left: 0;
  bottom: 0.1rem;
  font-size: 0.625rem;
`;

const StyledMiddleTypography = styled(Typography)`
  position: absolute;
  left: 0;
  top: 50%;
  transform: translate(0, -50%);
  font-size: 0.625rem;
`;
*/

// https://github.com/plouc/nivo/issues/308#issuecomment-451280930
const theme = {
  tooltip: {
    container: {
      color: 'rgba(0, 0, 0, 0.87)',
    },
  },
  axis: {
    ticks: {
      text: {
        fill: 'rgba(255,255,255,0.5)',
      },
    },
  },
};

type Aggregate = {
  interval: number; // interval second
  count: number; // number of intervals
  offset?: number;
};

/*
type Point = {
  value: number;
  timestamp: number;
};

function aggregatePoints(
  points: Point[],
  interval: number, // interval second
  count: number, // number of intervals
  offset: number = 0,
) {
  let current = Date.now() / 1000;

  const items = [];

  for (let i = -count; i < 0; i += 1) {
    const start = current + i * interval - offset;
    const end = current + (i + 1) * interval - offset;

    const item = {
      start,
      end,
      timestamp: start,
      value: 0,
    };

    points.forEach((pointItem) => {
      const { timestamp, value } = pointItem;

      if (timestamp > start && timestamp <= end) {
        item.value += value;
      }
    });

    items.push(item);
  }

  return items;
}
*/

function generateTransactionGraphData(
  transactions: Transaction[],
): {
  value: number;
  timestamp: number;
}[] {
  // use only confirmed transactions
  const confirmedTransactions = transactions.filter(
    (transaction) => transaction.confirmed,
  );

  const [peakTransaction] = confirmedTransactions;

  // extract and compute values
  let results = confirmedTransactions.map<{
    value: number;
    timestamp: number;
  }>((transaction) => {
    const { type, confirmedAtHeight, amount, feeAmount } = transaction;

    const isOutgoing = [
      TransactionType.OUTGOING,
      TransactionType.OUTGOING_TRADE,
    ].includes(type);

    const value = (amount + feeAmount) * (isOutgoing ? -1 : 1);

    return {
      value,
      timestamp: blockHeightToTimestamp(confirmedAtHeight, peakTransaction),
    };
  });

  // group transactions by confirmed_at_height
  const groupedResults = groupBy(results, 'timestamp');

  // sum grouped transaction and extract just valuable information
  results = map(groupedResults, (items, timestamp) => ({
    timestamp: Number(timestamp),
    value: sumBy(items, 'value'),
  }));

  // order by timestamp
  results = orderBy(results, ['timestamp'], ['desc']);

  return results;
}

function prepareGraphPoints(
  balance: number,
  transactions: Transaction[],
  aggregate?: Aggregate,
): {
  x: number;
  y: number;
  tooltip?: ReactNode;
}[] {
  if (!transactions || !transactions.length) {
    return [];
  }

  let start = balance;
  const data = generateTransactionGraphData(transactions);

  const [peakTransaction] = transactions;

  /*
  if (aggregate) {
    const { interval, count, offset } = aggregate;
    data = aggregatePoints(data, interval, count, offset);
  }
  */

  const points = [
    {
      x: peakTransaction.confirmedAtHeight,
      y: Math.max(0, Number(mojoToChia(start))),
      tooltip: mojoToChia(balance),
    },
  ];

  data.forEach((item) => {
    const { timestamp, value } = item;

    start = start - value;

    points.push({
      x: timestamp,
      y: Math.max(0, Number(mojoToChia(start))),
      tooltip: mojoToChia(start),
    });
  });

  return points.reverse();
}

type Props = {
  walletId: number;
  height?: number | string;
};

export default function WalletGraph(props: Props) {
  const { walletId, height } = props;
  const { transactions, isLoading: isWalletTransactionsLoading } = useWalletTransactions(walletId, 50, 0, 'RELEVANCE');
  const { 
    data: walletBalance, 
    isLoading: isWalletBalanceLoading,
  } = useGetWalletBalanceQuery({
    walletId,
  });

  const isLoading = isWalletTransactionsLoading || isWalletBalanceLoading || !transactions;
  if (isLoading || !walletBalance) {
    return null;
  }

  const confirmedTransactions = transactions.filter((transaction) => transaction.confirmed);
  if (!confirmedTransactions.length) {
    return null;
  }

  const balance = walletBalance.confirmedWalletBalance;

  const points = prepareGraphPoints(balance, confirmedTransactions, {
    interval: 60 * 60,
    count: 24,
    offset: 0,
  });

  const data = [{
    id: 'Points',
    data: points,
  }];

  const min = points.length ? Math.min(...points.map((item) => item.y)) : 0;
  const max = Math.max(min, ...points.map((item) => item.y));
  // const middle = max / 2;

  return (
    <StyledGraphContainer height={height}>
      <ResponsiveLine
        margin={{ left: 0, top: 2, bottom: 2, right: 0 }}
        data={data}
        theme={theme}
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
        xScale={{
          type: 'point',
        }}
        colors={{ scheme: 'accent' }}
        axisTop={null}
        axisRight={null}
        axisBottom={
          null /* {
          tickValues: "every 1 second",
          tickSize: 5,
          tickPadding: 5,
          tickRotation: 0,
          format: "%S.%L",
          legend: "Time",
          legendOffset: 36,
          legendPosition: "middle"
        } */
        }
        axisLeft={null}
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
      {/* 
      <StyledMaxTypography variant="body2" color="textSecondary">
        <FormatLargeNumber value={max} />
      </StyledMaxTypography>

      <StyledMinTypography variant="body2" color="textSecondary">
        <FormatLargeNumber value={min} />
      </StyledMinTypography>

      <StyledMiddleTypography variant="body2" color="textSecondary">
        <FormatLargeNumber value={middle} />
      </StyledMiddleTypography>
      */}
    </StyledGraphContainer>
  );
}

WalletGraph.defaultProps = {
  height: 150,
};
