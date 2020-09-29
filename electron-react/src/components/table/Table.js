import React from "react";
import PropTypes from "prop-types";

import { withStyles, makeStyles } from "@material-ui/core/styles";
import MUITable from "@material-ui/core/Table";
import TableContainer from "@material-ui/core/TableContainer";
import TableHead from "@material-ui/core/TableHead";
import TableBody from "@material-ui/core/TableBody";
import TableRow from "@material-ui/core/TableRow";
import TableCell from "@material-ui/core/TableCell";
import Paper from "@material-ui/core/Paper";

import Tooltip from "../tooltip";

const StyledTableCell = withStyles((theme) => ({
  head: {
    backgroundColor: theme.palette.grey[200],
    padding: "20px",

    fontWeight: 500,
    fontSize: "24px",
    lineHeight: "28px",
    letterSpacing: "0.685741px",

    color: "#111111",
  },
  body: {
    fontWeight: "normal",
    fontSize: "22px",
    lineHeight: "26px",
    textAlign: "center",
    letterSpacing: "0.575px",

    color: "#66666B",

    whiteSpace: "nowrap",
  },
  root: {
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
}))(TableCell);

export const SingleRowTableCell = withStyles((theme) => ({
  root: {
    border: "1px solid",
    borderColor: theme.palette.grey[200],
  },
}))(StyledTableCell);

export const StyledTableRow = withStyles((theme) => ({
  root: {
    "&:nth-of-type(even)": {
      backgroundColor: "#FAFAFA",
    },
  },
}))(TableRow);

const useStyles = makeStyles({
  table: {
    width: "100%",
    tableLayout: "fixed",
    overflow: "hidden",
  },
  tooltip: {
    fontFamily: "Avenir Next Condensed, sans-serif",
    fontWeight: "600",
    fontSize: "16px",
  },
  cellAnnotation: {
    fontSize: "16px",
    lineHeight: "19px",
    whiteSpace: "pre-wrap",
  },
});

/**
 * General table component to display data in a tabular way.
 */
function Table(props) {
  const { header, data } = props;

  const isSingleRow = !Array.isArray(data[0]);

  const rowData = isSingleRow ? [data] : data;

  const TableCellComp = isSingleRow ? SingleRowTableCell : StyledTableCell;

  const classes = useStyles();

  return (
    <TableContainer component={Paper}>
      <MUITable className={classes.table}>
        <TableHead>
          <TableRow>
            {header.map((h) => (
              <StyledTableCell key={h} align="center">
                {h}
              </StyledTableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rowData.map((row, rowIdx) => (
            <StyledTableRow key={rowIdx}>
              {row.map((entry, cellIdx) => {
                let cellContent = entry;
                let cellAnnotation;

                if (typeof entry === "object") {
                  cellContent = entry.content;
                  cellAnnotation = entry.annotation;
                }

                return (
                  <Tooltip
                    key={`${rowIdx}_${cellIdx}`}
                    arrow
                    placement="bottom"
                    interactive
                    title={<div className={classes.tooltip}>{cellContent}</div>}
                  >
                    <TableCellComp align="center">
                      {cellContent}
                      {cellAnnotation && (
                        <div className={classes.cellAnnotation}>
                          {cellAnnotation}
                        </div>
                      )}
                    </TableCellComp>
                  </Tooltip>
                );
              })}
            </StyledTableRow>
          ))}
        </TableBody>
      </MUITable>
    </TableContainer>
  );
}

Table.propTypes = {
  header: PropTypes.arrayOf(
    PropTypes.oneOfType([PropTypes.string, PropTypes.object])
  ).isRequired,
  data: PropTypes.arrayOf(
    PropTypes.arrayOf(PropTypes.oneOfType([PropTypes.string, PropTypes.number]))
  ).isRequired,
};

export default Table;
