import React, { ReactNode } from 'react';
import { linearGradientDef } from '@nivo/core';
import { ResponsiveLine } from '@nivo/line';
import { orderBy } from 'lodash';
import { Flex, FormatLargeNumber } from '@chia/core';
import { Typography, Paper } from '@material-ui/core';
import styled from 'styled-components';
import useWallet from '../../hooks/useWallet';
import TransactionType from '../../constants/TransactionType';
import type Transaction from '../../types/Transaction';
import { mojo_to_chia } from '../../util/chia';

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

function preparePoints(balance: number, transactions: Transaction[]): {
  x: number;
  y: number;
  tooltip?: ReactNode;
}[] {
  let current = Date.now() / 1000;

  console.log('balance', balance);
  console.log('transactions', transactions);

  const points = [];

  if (!transactions || !transactions.length) {
    return points;
  }

  const ordered = orderBy(transactions, ['confirmed_at_height'], ['desc']);

  let start = balance;

  points.push({
    x: 1,
    y: mojo_to_chia(start),
    tooltip: mojo_to_chia(balance),
  });

  ordered.forEach((item, index) => {
    const { type, created_at_time, confirmed_at_height, amount, fee_amount, confirmed } = item;

    if (!confirmed) {
      return;
    }

    const isOutgoing = [
      TransactionType.OUTGOING, 
      TransactionType.OUTGOING_TRADE,
    ].includes(type);

    const total = (amount + fee_amount) * (isOutgoing ? -1 : 1);

    start = start - total;

    points.push({
      x: confirmed_at_height,
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
  const { wallet, transactions } = useWallet(walletId);
  const balance = wallet?.wallet_balance?.confirmed_wallet_balance;
  if (!transactions || !balance) {
    return null;
  }

  const points = preparePoints(balance, transactions);
  

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
