import React from 'react';
import { Box, BoxProps } from '@mui/material';
import { useTheme } from '@mui/material/styles';
import styled from 'styled-components';

type GAP_SIZE = number | string | 'small' | 'normal' | 'large';

function getGap(gap: GAP_SIZE, theme: any): string {
  if (typeof gap === 'number') {
    return `${theme.spacing(gap)}`;
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
  > *:not(:last-child) {
    ${({ rowGap, flexDirection }) => rowGap && `margin-${flexDirection === 'column-reverse' ? 'top' : 'bottom'}: ${rowGap}`};
    ${({ columnGap, flexDirection }) => columnGap && `margin-${flexDirection === 'row-reverse' ? 'left' : 'right'}: ${columnGap}`};
  }
`;

export type FlexProps = BoxProps & {
  gap?: GAP_SIZE;
  rowGap?: GAP_SIZE;
  columnGap?: GAP_SIZE;
  inline?: boolean;
};

export default function Flex(props: FlexProps) {
  const {
    gap = '0',
    flexDirection,
    rowGap = gap,
    columnGap = gap,
    inline = false,
    ...rest
  } = props;

  const theme = useTheme();

  const rowGapValue = ['column', 'column-reverse'].includes(flexDirection)
    ? getGap(rowGap, theme)
    : 0;

  const columnGapValue = !['column', 'column-reverse'].includes(flexDirection)
    ? getGap(columnGap, theme)
    : 0;

  return (
    <StyledGapBox
      display={inline ? 'inline-flex' : 'flex'}
      flexDirection={flexDirection}
      rowGap={rowGapValue}
      columnGap={columnGapValue}
      {...rest}
    />
  );
}
