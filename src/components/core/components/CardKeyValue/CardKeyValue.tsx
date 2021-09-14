import React, { ReactNode } from 'react';
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableRow,
} from '@material-ui/core';
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

type Props = {
  rows: {
    key: string;
    label: ReactNode;
    value: ReactNode;
  }[];
  label?: string;
  hideDivider?: boolean;
  size?: 'small' | 'normal' | 'large';
};

export default function CardKeyValue(props: Props) {
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
            <StyledTableCell align="right" hideDivider={hideDivider}>
              <Box maxWidth="100%">
                <Typography component='div' variant="body2" noWrap>
                  {row.value}
                </Typography>
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
