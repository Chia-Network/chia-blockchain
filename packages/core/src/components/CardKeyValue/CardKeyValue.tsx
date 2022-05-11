import React, { ReactNode } from 'react';
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableRow,
} from '@mui/material';
import styled from 'styled-components';

const StyledTableCell= styled(({ hideDivider, ...rest }) => (
  <TableCell {...rest}/>
))`
  ${({ hideDivider }) =>
    hideDivider
      ? `
      border-bottom: 0px solid transparent;
      padding-left: 0;
      padding-right: 0 !important;
    `
      : ''}
`;

export type CardKeyValueProps = {
  rows: {
    key: string;
    label: ReactNode;
    value: ReactNode;
  }[];
  label?: string;
  hideDivider?: boolean;
  size?: 'small' | 'normal' | 'large';
};

export default function CardKeyValue(props: CardKeyValueProps) {
  const { rows, label, hideDivider, size } = props;

  return (
    <Table size={size} aria-label={label}>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.key}>
            <StyledTableCell hideDivider={hideDivider}>
              <Typography component='div' variant="body1" color="textSecondary" noWrap>
                {row.label}
              </Typography>
            </StyledTableCell>
            <StyledTableCell hideDivider={hideDivider} width="100%">
              <Box ml={2} position="relative">
                <Box position="absolute" left="0" top="0" bottom="0" right="0" display="flex" alignItems="center" justifyContent="flex-end">
                  <Typography component='div' variant="body2" noWrap>
                    {row.value}
                  </Typography>
                </Box>
              </Box>
            </StyledTableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

CardKeyValue.defaultProps = {
  label: undefined,
  hideDivider: false,
  size: 'small',
};
