import React, { ReactNode } from 'react';
import { linearGradientDef } from '@nivo/core';
import { ResponsiveLine } from '@nivo/line';
import { orderBy, groupBy, sumBy, map } from 'lodash';
import { Flex, FormatLargeNumber } from '@chia/core';
import { Typography, Paper } from '@material-ui/core';
import styled from 'styled-components';
import useWallet from '../../hooks/useWallet';
import TransactionType from '../../constants/TransactionType';
import type Transaction from '../../types/Transaction';
import type Peak from '../../types/Peak';
import { mojo_to_chia } from '../../util/chia';
import usePeak from '../../hooks/usePeak';
import blockHeightToTimestamp from '../../util/blockHeightToTimestamp';

const StyledRoot = styled.div`
  // border-radius: 1rem;
  // background-color: #303030;
  // padding: 1rem;
`;

const StyledGraphContainer = styled.div`
  position: relative;
  height: 150px;
`;

const StyledTooltip = styled(Paper)`
  padding: 0.25rem 0.5rem;
`;

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

function generateTransactionGraphData(transactions: Transaction[], peak: Peak): {
  value: number;
  timestamp: number;
}[] {
  // use only confirmed transactions
  const confirmedTransactions = transactions.filter(transaction => transaction.confirmed);

  // extract and compute values
  let results = confirmedTransactions.map<{
    value: number;
    timestamp: number;
  }>((transaction) => {
    const { type, confirmed_at_height, amount, fee_amount } = transaction;

    const isOutgoing = [
      TransactionType.OUTGOING, 
      TransactionType.OUTGOING_TRADE,
    ].includes(type);

    const value = (amount + fee_amount) * (isOutgoing ? -1 : 1);

    return {
      value,
      timestamp: blockHeightToTimestamp(confirmed_at_height, peak)
    };
  });

  // group transactions by confirmed_at_height
  const groupedResults = groupBy(results, 'timestamp');

  // sum grouped transaction and extract just valuable information
  results = map(groupedResults, (items, timestamp) => ({
    timestamp,
    value: sumBy(items, 'value'),
  }));

  // order by timestamp
  results = orderBy(results, ['timestamp'], ['desc']);

  return results;
}

function prepareGraphPoints(balance: number, transactions: Transaction[], peak: Peak): {
  x: number;
  y: number;
  tooltip?: ReactNode;
}[] {
  if (!transactions || !transactions.length || !peak) {
    return [];
  }

  let start = balance;
  const data = generateTransactionGraphData(transactions, peak);

  const points = [{
    x: peak.height,
    y: mojo_to_chia(start),
    tooltip: mojo_to_chia(balance),
  }];

  data.forEach((item) => {
    const { timestamp, value } = item;

    start = start - value;

    points.push({
      x: timestamp,
      y: mojo_to_chia(start),
      tooltip: mojo_to_chia(start),
    });
  });

  return points.reverse();
}

type Props = {
  walletId: number;
};

export default function WalletGraph(props: Props) {
  const { walletId } = props;
  const { peak } = usePeak();
  const { wallet, transactions } = useWallet(walletId);
  const balance = wallet?.wallet_balance?.confirmed_wallet_balance;
  if (!transactions || !balance || !peak) {
    return null;
  }

  const points = prepareGraphPoints(balance, transactions, peak);
  
  const data = [{
    id: 'Points',
    data: points,
  }];
  
  const min = points.length ? Math.min(...points.map(item => item.y)) : 0;
  const max = Math.max(min, ...points.map(item => item.y));
  const middle = max / 2;

  return (
    <StyledGraphContainer>
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
        axisBottom={null /* {
          tickValues: "every 1 second",
          tickSize: 5,
          tickPadding: 5,
          tickRotation: 0,
          format: "%S.%L",
          legend: "Time",
          legendOffset: 36,
          legendPosition: "middle"
        } */}

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
