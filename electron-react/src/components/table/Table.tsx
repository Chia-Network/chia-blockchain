import React, { ReactNode } from 'react';
import styled from 'styled-components';
import {
  TableContainer,
  TableHead,
  Table as TableBase,
  TableBody,
  TableRow,
  TableCell,
  Paper,
} from '@material-ui/core';

const StyledTableHead = styled(TableHead)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#202020' : '#eeeeee'};
  font-weight: 500;
`;

const StyledTableRow = styled(TableRow)`
  &:nth-of-type(even) {
    background-color: ${({ theme }) =>
      theme.palette.type === 'dark' ? '#515151' : '#FAFAFA'};
  }
`;

const StyledTableCell = styled(({ width, minWidth, maxWidth, ...rest }) => (
  <TableCell {...rest} />
))`
  max-width: ${({ maxWidth, width }) => (maxWidth ? maxWidth : width ?? '0')};
  min-width: ${({ minWidth }) => (minWidth ? minWidth : '0')};
  width: ${({ width }) => (width ? width : 'auto')};
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export type Row = {
  [key: string]: any;
};

type Props = {
  cols: {
    field: ReactNode | ((row: Row) => ReactNode);
    title: ReactNode;
    minWidth?: string;
    maxWidth?: string;
    width?: string;
  }[];
  rows: Row[];
};

export default function Table(props: Props) {
  const { cols, rows } = props;

  return (
    <TableContainer component={Paper}>
      <TableBase>
        <StyledTableHead>
          <TableRow>
            {cols.map((col, colIndex) => (
              <StyledTableCell
                key={`${col.field}-${colIndex}`}
                minWidth={col.minWidth}
                maxWidth={col.maxWidth}
                width={col.width}
              >
                {col.title}
              </StyledTableCell>
            ))}
          </TableRow>
        </StyledTableHead>
        <TableBody>
          {rows.map((row, rowIndex) => (
            <StyledTableRow key={`${row.id}-${rowIndex}`}>
              {cols.map((col, colIndex) => {
                const { field } = col;
                const value =
                  typeof field === 'function'
                    ? field(row)
                    : // @ts-ignore
                      row[field];

                return (
                  <StyledTableCell
                    minWidth={col.minWidth}
                    maxWidth={col.maxWidth}
                    width={col.width}
                  >
                    {value}
                  </StyledTableCell>
                );
              })}
            </StyledTableRow>
          ))}
        </TableBody>
      </TableBase>
    </TableContainer>
  );
}
