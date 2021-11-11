import React, { ReactNode, useMemo, useState, SyntheticEvent, Fragment } from 'react';
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
  Collapse,
} from '@material-ui/core';

const StyledTableHead = styled(TableHead)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#202020' : '#eeeeee'};
  font-weight: 500;
`;

export const StyledTableRow = styled(TableRow)`
  &:nth-of-type(3n) {
    background-color: ${({ theme }) =>
      theme.palette.type === 'dark' ? '#515151' : '#FAFAFA'};
  }
`;

const StyledExpandedTableRow = styled(TableRow)`
  background-color: ${({ theme }) =>
    theme.palette.type === 'dark' ? '#1E1E1E' : '#EEEEEE'};
`;

const StyledTableCell = styled(({ width, minWidth, maxWidth, ...rest }) => (
  <TableCell {...rest} />
))`
  max-width: ${({ minWidth, maxWidth, width }) =>
    (maxWidth || width || minWidth) ?? 'none'};
  min-width: ${({ minWidth }) => minWidth || '0'};
  width: ${({ width, minWidth }) => (width || minWidth ? width : 'auto')}};
`;

const StyledTableCellContent = styled.div`
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
`;

const StyledExpandedTableCell = styled(TableCell)`
  ${({ isExpanded }) => !isExpanded ? 'border: 0;' : undefined}
`;

const StyledExpandedTableCellContent = styled.div`
  padding: 1rem 0;
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
  uniqueField?: string;
  metadata?: any;
  expandedField?: (row: Row) => ReactNode;
  expandedCellShift?: number;
};

export default function Table(props: Props) {
  const {
    cols,
    rows,
    children,
    pages,
    rowsPerPageOptions,
    rowsPerPage: defaultRowsPerPage,
    hideHeader,
    caption,
    onRowClick,
    rowHover,
    uniqueField,
    metadata,
    expandedField,
    expandedCellShift,
  } = props;
  const [expanded, setExpanded] = useState<{
    [key: string]: boolean;
  }>({});
  const [page, setPage] = useState<number>(0);
  const [rowsPerPage, setRowsPerPage] = useState<number>(
    defaultRowsPerPage ?? 10,
  );

  function handleToggleExpand(rowId: string) {
    setExpanded({
      ...expanded,
      [rowId]: !expanded[rowId],
    });
  }

  function handleChangePage(
    event: React.MouseEvent<HTMLButtonElement, MouseEvent> | null,
    newPage: number,
  ) {
    setPage(newPage);
  }

  function handleChangeRowsPerPage(
    event: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>,
  ) {
    setRowsPerPage(+event.target.value);
    setPage(0);
  }

  const currentCols = useMemo<InternalTableCol[]>(
    () =>
      cols.map((col, index) => ({
        key: index,
        ...col,
      })),
    [cols],
  );

  const preparedRows = useMemo<InternalTableRow[]>(
    () =>
      rows.map((row, rowIndex) => ({
        $uniqueId: uniqueField ? get(row, uniqueField) : rowIndex,
        ...row,
      })),
    [rows],
  );

  const currentRows = useMemo<InternalTableRow[]>(() => {
    if (!pages) {
      return preparedRows;
    }

    return preparedRows.slice(
      page * rowsPerPage,
      page * rowsPerPage + rowsPerPage,
    );
  }, [preparedRows, pages, page, rowsPerPage]);

  function handleRowClick(e: SyntheticEvent, row: Row) {
    if (onRowClick) {
      onRowClick(e, row);
    }
  }

  return (
    <TableContainer component={Paper}>
      <TableBase>
        {caption && <caption>{caption}</caption>}
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
                  <StyledTableCellContent>{col.title}</StyledTableCellContent>
                </StyledTableCell>
              ))}
            </TableRow>
          </StyledTableHead>
        )}
        <TableBody>
          {children}
          {currentRows.map((row) => {
            const id = row.$uniqueId.toString();
            const isExpanded = !!expanded[id];
            const expandableCells = [];

            for (let i = 0; i < expandedCellShift; i += 1) {
              expandableCells.push((
                <StyledExpandedTableCell key={i} style={{ paddingBottom: 0, paddingTop: 0 }} isExpanded={isExpanded}>
                </StyledExpandedTableCell>
              ));
            }

            return (
              <Fragment key={id}>
                <StyledTableRow
                  
                  onClick={(e) => handleRowClick(e, row)}
                  hover={rowHover}
                >
                  {currentCols.map((col) => {
                    const { field, tooltip } = col;

                    const value =
                      typeof field === 'function'
                        ? field(row, metadata, isExpanded, () => handleToggleExpand(id))
                        : // @ts-ignore
                          get(row, field);

                    let tooltipValue;
                    if (tooltip) {
                      if (tooltip === true) {
                        tooltipValue = value;
                      } else {
                        tooltipValue =
                          typeof tooltip === 'function'
                            ? tooltip(row)
                            : // @ts-ignore
                              get(row, tooltip);
                      }
                    }

                    return (
                      <StyledTableCell
                        minWidth={col.minWidth}
                        maxWidth={col.maxWidth}
                        width={col.width}
                        key={col.key}
                        isExpanded={isExpanded}
                      >
                        {tooltipValue ? (
                          <Tooltip title={tooltipValue}>
                            <StyledTableCellContent>{value}</StyledTableCellContent>
                          </Tooltip>
                        ) : (
                          <StyledTableCellContent>{value}</StyledTableCellContent>
                        )}
                      </StyledTableCell>
                    );
                  })}
                </StyledTableRow>
                <StyledExpandedTableRow>
                  {expandableCells}
                  <StyledExpandedTableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={cols.length - expandedCellShift} isExpanded={isExpanded}>
                    <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                      <StyledExpandedTableCellContent>
                        {expandedField && expandedField(row)}
                      </StyledExpandedTableCellContent>
                    </Collapse>
                  </StyledExpandedTableCell>
                </StyledExpandedTableRow>
              </Fragment>
            );
          })}
        </TableBody>
      </TableBase>
      {pages && (
        <TablePagination
          rowsPerPageOptions={rowsPerPageOptions}
          component="div"
          count={rows.length ?? 0}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={handleChangePage}
          onRowsPerPageChange={handleChangeRowsPerPage}
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
  uniqueField: undefined,
  metadata: undefined,
  expandable: false,
  expandedCellShift: 0,
};
