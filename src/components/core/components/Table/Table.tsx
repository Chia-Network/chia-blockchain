import React, { ReactNode, useMemo, useState, SyntheticEvent } from 'react';
import styled from 'styled-components';
import { get } from 'lodash';
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
  max-width: ${({ minWidth, maxWidth, width }) => ((maxWidth || width || minWidth) ?? 'none')};
  min-width: ${({ minWidth }) => (minWidth || '0')};
  width: ${({ width, minWidth }) => width || minWidth ? width : 'auto'}};
`;

const StyledTableCellContent = styled.div`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

export type Col = {
  key?: number | string;
  field: ReactNode | ((row: Row) => ReactNode);
  title: ReactNode;
  minWidth?: string;
  maxWidth?: string;
  width?: string;
  tooltip?: ReactNode | ((row: Row) => ReactNode);
};

export type Row = {
  [key: string]: any;
};

type InternalTableCol = Col & { key: string | number };

type InternalTableRow = Row & { id: string | number };

type Props = {
  cols: Col[];
  rows: Row[];
  children?: ReactNode;
  pages?: boolean;
  rowsPerPageOptions?: number[];
  rowsPerPage?: number;
  hideHeader?: boolean;
  caption?: ReactNode;
  onRowClick?: (e: SyntheticEvent, row: Row) => void;
  rowHover?: boolean;
};

export default function Table(props: Props) {
  const { cols, rows, children, pages, rowsPerPageOptions, rowsPerPage: defaultRowsPerPage, hideHeader, caption, onRowClick, rowHover } = props;
  const [page, setPage] = useState<number>(0);
  const [rowsPerPage, setRowsPerPage] = useState<number>(defaultRowsPerPage ?? 10);

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

  const currentCols = useMemo<InternalTableCol[]>(() => cols.map((col, index) => ({
    key: index,
    ...col,
  })), [cols]);

  const preparedRows = useMemo<InternalTableRow[]>(() => rows.map((row, rowIndex) => ({
    id: rowIndex,
    ...row,
  })), [rows]);

  const currentRows = useMemo<InternalTableRow[]>(() => {
    if (!pages) {
      return preparedRows;
    }

    return preparedRows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);
  }, [preparedRows, pages, page, rowsPerPage]);

  function handleRowClick(e: SyntheticEvent, row: Row) {
    if (onRowClick) {
      onRowClick(e, row);
    }
  }

  return (
    <TableContainer component={Paper}>
      <TableBase>
        {caption && (
          <caption>{caption}</caption>
        )}
        {!hideHeader && (
          <StyledTableHead>
            <TableRow>
              {currentCols.map((col) => (
                <StyledTableCell
                  key={col.key}
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
          {currentRows.map((row) => (
            <StyledTableRow 
              key={row.id} 
              onClick={(e) => handleRowClick(e, row)} 
              hover={rowHover}
            >
              {currentCols.map((col) => {
                const { field, tooltip } = col;
                const value =
                  typeof field === 'function'
                    ? field(row)
                    : // @ts-ignore
                      get(row, field);

                let tooltipValue;
                if (tooltip) {
                  if (tooltip === true) {
                    tooltipValue = value;
                  } else {
                    tooltipValue = typeof tooltip === 'function'
                    ? tooltip(row)
                    : // @ts-ignore
                      row[tooltip];
                  }
                }

                return (
                  <StyledTableCell
                    minWidth={col.minWidth}
                    maxWidth={col.maxWidth}
                    width={col.width}
                    key={col.key}
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
  caption: undefined,
  children: undefined,
  rowHover: false,
};
