import React from 'react';
import { Box, BoxProps } from '@material-ui/core';
import { useTheme } from '@material-ui/core/styles';
import styled from 'styled-components';

type GAP_SIZE = number | string | 'small' | 'normal' | 'large';

function getGap(gap: GAP_SIZE, theme: any): string {
  if (typeof gap === 'number') {
    return `${theme.spacing(gap)}px`;
  }

  switch (gap) {
    case 'small':
      return '0.5rem';
    case 'normal':
      return '1rem';
    case 'large':
      return '2rem';
    default:
      return String(gap);
  }
}

const StyledGapBox = styled(({ rowGap, columnGap, ...rest }) => (
  <Box {...rest} />
))`
  > * {
    margin-bottom: ${({ rowGap }) => rowGap};
    ${({ columnGap }) => columnGap && `margin-right: ${columnGap}`};

    &:last-child {
      margin-bottom: 0;
      ${({ columnGap }) => columnGap && `margin-right: 0`};
    }
  }
`;

type Props = BoxProps & {
  gap?: GAP_SIZE;
  rowGap?: GAP_SIZE;
  columnGap?: GAP_SIZE;
};

export default function Flex(props: Props) {
  const {
    gap = '0px',
    flexDirection,
    rowGap = gap,
    columnGap = gap,
    ...rest
  } = props;

  const theme = useTheme();

  const rowGapValue = flexDirection === 'column' ? getGap(rowGap, theme) : 0;

  const columnGapValue =
    flexDirection !== 'column' ? getGap(columnGap, theme) : 0;

  return (
    <StyledGapBox
      display="flex"
      flexDirection={flexDirection}
      rowGap={rowGapValue}
      columnGap={columnGapValue}
      {...rest}
    />
  );
}
