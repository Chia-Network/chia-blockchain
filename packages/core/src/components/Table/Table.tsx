import React, { ReactNode, useMemo, useState, SyntheticEvent, Fragment } from 'react';
import TableControlled, { TableControlledProps, InternalTableRow } from './TableControlled';

type Props = TableControlledProps;

export default function Table(props: Props) {
  const {
    rows,
    page: defaultPage,
    pages,
    rowsPerPage: defaultRowsPerPage,
    ...rest
  } = props;
  const [expanded, setExpanded] = useState<{
    [key: string]: boolean;
  }>({});
  const [page, setPage] = useState<number>(defaultPage ?? 0);
  const [rowsPerPage, setRowsPerPage] = useState<number>(
    defaultRowsPerPage ?? 10,
  );

  function handleToggleExpand(rowId: string) {
    setExpanded({
      ...expanded,
      [rowId]: !expanded[rowId],
    });
  }

  function handlePageChange(newRowsPerPage: number, newPage: number) {
    setPage(newPage);
    setRowsPerPage(newRowsPerPage);
  }

  const visibleRows = useMemo<InternalTableRow[]>(() => {
    if (!pages) {
      return rows;
    }

    return rows.slice(
      page * rowsPerPage,
      page * rowsPerPage + rowsPerPage,
    );
  }, [rows, pages, page, rowsPerPage]);


  return (
    <TableControlled
      rows={visibleRows}
      onPageChange={handlePageChange}
      page={page}
      rowsPerPage={rowsPerPage}
      pages={pages}
      count={rows.length}
      {...rest}
    />
  );
}

Table.defaultProps = {
  rows: [],
  pages: false,
  page: 0,
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
