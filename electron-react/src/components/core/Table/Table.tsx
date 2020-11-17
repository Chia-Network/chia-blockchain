import React, { ReactNode, useMemo, useState } from 'react';
import styled from 'styled-components';
import {
  TableContainer,
  TableHead,
  Table as TableBase,
  TableBody,
  TableRow,
  TableCell,
  Paper,
  Tooltip,
  TablePagination,
} from '@material-ui/core';

const StyledTableHead = styled(TableHead)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#202020' : '#eeeeee'};
  font-weight: 500;
`;

export const StyledTableRow = styled(TableRow)`
  &:nth-of-type(even) {
    background-color: ${({ theme }) =>
      theme.palette.type === 'dark' ? '#515151' : '#FAFAFA'};
  }
`;

const StyledTableCell = styled(({ width, minWidth, maxWidth, ...rest }) => (
  <TableCell {...rest} />
))`
  max-width: ${({ maxWidth, width }) => ((maxWidth || width) ?? '0')};
  min-width: ${({ minWidth }) => (minWidth || '0')};
  width: ${({ width }) => (width || 'auto')};
`;

const StyledTableCellContent = styled.div`
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
    tooltip?: ReactNode | ((row: Row) => ReactNode);
  }[];
  rows: Row[];
  children?: ReactNode;
  pages?: boolean;
  rowsPerPageOptions?: number[];
  rowsPerPage: number;
  hideHeader?: boolean;
};

export default function Table(props: Props) {
  const { cols, rows, children, pages, rowsPerPageOptions, rowsPerPage: defaultRowsPerPage, hideHeader } = props;
  const [page, setPage] = useState<number>(0);
  const [rowsPerPage, setRowsPerPage] = useState<number>(defaultRowsPerPage);

  function handleChangePage(
    event: React.MouseEvent<HTMLButtonElement, MouseEvent> | null,
    newPage: number,
  ) {
    setPage(newPage);
  }

  function handleChangeRowsPerPage (
    event: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>,
  ) {
    setRowsPerPage(+event.target.value);
    setPage(0);
  }

  const currentRows = useMemo(() => {
    if (!pages) {
      return rows;
    }

    return rows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);
  }, [rows, pages, page, rowsPerPage]);

  return (
    <TableContainer component={Paper}>
      <TableBase>
        {!hideHeader && (
          <StyledTableHead>
            <TableRow>
              {cols.map((col, colIndex) => (
                <StyledTableCell
                  key={`${col.field}-${colIndex}`}
                  minWidth={col.minWidth}
                  maxWidth={col.maxWidth}
                  width={col.width}
                >
                  <StyledTableCellContent>
                    {col.title}
                  </StyledTableCellContent>
                </StyledTableCell>
              ))}
            </TableRow>
          </StyledTableHead>
        )}
        <TableBody>
          {children}
          {currentRows.map((row, rowIndex) => (
            <StyledTableRow key={`${row.id}-${rowIndex}`}>
              {cols.map((col, colIndex) => {
                const { field, tooltip } = col;
                const value =
                  typeof field === 'function'
                    ? field(row)
                    : // @ts-ignore
                      row[field];

                let tooltipValue;
                if (tooltip) {
                  tooltipValue = typeof tooltip === 'function'
                    ? tooltip(row)
                    : // @ts-ignore
                      row[tooltip];
                }

                return (
                  <StyledTableCell
                    minWidth={col.minWidth}
                    maxWidth={col.maxWidth}
                    width={col.width}
                    key={colIndex}
                  >
                    {tooltipValue ? (
                      <Tooltip title={tooltipValue}>
                        <StyledTableCellContent>
                          {value}
                        </StyledTableCellContent>
                      </Tooltip>
                    ) : (
                    <StyledTableCellContent>
                      {value}
                    </StyledTableCellContent>
                    )}
                  </StyledTableCell>
                );
              })}
            </StyledTableRow>
          ))}
        </TableBody>
      </TableBase>
      {pages && (
        <TablePagination
          rowsPerPageOptions={rowsPerPageOptions}
          component="div"
          count={rows.length ?? 0}
          rowsPerPage={rowsPerPage}
          page={page}
          onChangePage={handleChangePage}
          onChangeRowsPerPage={handleChangeRowsPerPage}
        />
      )}
    </TableContainer>
  );
}

Table.defaultProps = {
  pages: false,
  rowsPerPageOptions: [10, 25, 100],
  rowsPerPage: 10,
  hideHeader: false,
};
