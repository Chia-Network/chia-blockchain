import React, { ReactNode } from 'react';
import {
  VictoryChart,
  VictoryAxis,
  VictoryArea,
  VictoryTooltip,
  VictoryVoronoiContainer,
} from 'victory';
import BigNumber from 'bignumber.js';
import { orderBy, groupBy, map } from 'lodash';
import { useMeasure } from 'react-use';
import styled from 'styled-components';
import { useGetWalletBalanceQuery } from '@chia/api-react';
import { TransactionType } from '@chia/api';
import type { Transaction } from '@chia/api';
import {
  useCurrencyCode,
  mojoToChia,
  blockHeightToTimestamp,
} from '@chia/core';
import useWalletTransactions from '../hooks/useWalletTransactions';

const StyledGraphContainer = styled.div`
  position: relative;
  min-height: 80px;
  height: ${({ height }) =>
    typeof height === 'string' ? height : `${height}px`};
`;

type Aggregate = {
  interval: number; // interval second
  count: number; // number of intervals
  offset?: number;
};

function generateTransactionGraphData(transactions: Transaction[]): {
  value: BigNumber;
  timestamp: number;
}[] {
  // use only confirmed transactions
  const confirmedTransactions = transactions.filter(
    (transaction) => transaction.confirmed
  );

  const [peakTransaction] = confirmedTransactions;

  // extract and compute values
  let results = confirmedTransactions.map<{
    value: BigNumber;
    timestamp: number;
  }>((transaction) => {
    const { type, confirmedAtHeight, amount, feeAmount } = transaction;

    const isOutgoing = [
      TransactionType.OUTGOING,
      TransactionType.OUTGOING_TRADE,
    ].includes(type);

    const total = BigNumber(amount).plus(BigNumber(feeAmount));
    const value = isOutgoing ? total.negated() : total;

    return {
      value,
      timestamp: blockHeightToTimestamp(confirmedAtHeight, peakTransaction),
    };
  });

  // group transactions by confirmed_at_height
  const groupedResults = groupBy(results, 'timestamp');

  // sum grouped transaction and extract just valuable information
  results = map(groupedResults, (items, timestamp) => {
    const values = items.map((item) => item.value);

    return {
      timestamp: Number(timestamp),
      value: BigNumber.sum(...values),
    };
  });

  // order by timestamp
  results = orderBy(results, ['timestamp'], ['desc']);

  return results;
}

function prepareGraphPoints(
  balance: number,
  transactions: Transaction[],
  _aggregate?: Aggregate
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
      x: blockHeightToTimestamp(
        peakTransaction.confirmedAtHeight,
        peakTransaction
      ),
      y: BigNumber.max(0, mojoToChia(start)).toNumber(), // max 21,000,000 safe to number
      tooltip: mojoToChia(balance).toString(), // bignumber is not supported by react
    },
  ];

  data.forEach((item) => {
    const { timestamp, value } = item;

    start = start - value.toNumber();

    points.push({
      x: timestamp,
      y: BigNumber.max(0, mojoToChia(start)).toNumber(), // max 21,000,000 safe to number
      tooltip: mojoToChia(start).toString(), // bignumber is not supported by react
    });
  });

  return points.reverse();
}

function LinearGradient() {
  return (
    <linearGradient id="graph-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stopColor="rgba(92, 170, 98, 40%)" />
      <stop offset="100%" stopColor="rgba(92, 170, 98, 0%)" />
    </linearGradient>
  );
}

export type WalletGraphProps = {
  walletId: number;
  height?: number | string;
};

export default function WalletGraph(props: WalletGraphProps) {
  const { walletId, height = 150 } = props;
  const { transactions, isLoading: isWalletTransactionsLoading } =
    useWalletTransactions(walletId, 50, 0, 'RELEVANCE');
  const { data: walletBalance, isLoading: isWalletBalanceLoading } =
    useGetWalletBalanceQuery({
      walletId,
    });

  const currencyCode = useCurrencyCode();
  const [ref, containerSize] = useMeasure();

  const isLoading =
    isWalletTransactionsLoading || isWalletBalanceLoading || !transactions;
  if (isLoading || !walletBalance) {
    return null;
  }

  const confirmedTransactions = transactions.filter(
    (transaction) => transaction.confirmed
  );
  if (!confirmedTransactions.length) {
    return null;
  }

  const balance = walletBalance.confirmedWalletBalance;

  const data = prepareGraphPoints(balance, confirmedTransactions, {
    interval: 60 * 60,
    count: 24,
    offset: 0,
  });

  const min = data.length ? Math.min(...data.map((item) => item.y)) : 0;
  const max = Math.max(min, ...data.map((item) => item.y));

  return (
    <StyledGraphContainer height={height} ref={ref}>
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
          labels={({ datum }) =>
            `${datum.tooltip} ${currencyCode.toUpperCase()}`
          }
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
    </StyledGraphContainer>
  );
}
