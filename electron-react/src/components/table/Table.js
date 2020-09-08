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

const StyledTableCell = withStyles((theme) => ({
  head: {
    backgroundColor: theme.palette.grey[200],
    padding: "20px",

    fontWeight: 500,
    fontSize: "24px",
    lineHeight: "28px",
    letterSpacing: "0.685741px",

    color: "#111111",
    whiteSpace: "nowrap",
  },
  body: {
    fontWeight: "normal",
    fontSize: "22px",
    lineHeight: "26px",
    textAlign: "center",
    letterSpacing: "0.575px",

    color: "#66666B",
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
    minWidth: 700,
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
          {rowData.map((row) => (
            <StyledTableRow>
              {row.map((entry) => (
                <TableCellComp align="center">{entry}</TableCellComp>
              ))}
            </StyledTableRow>
          ))}
        </TableBody>
      </MUITable>
    </TableContainer>
  );
}

Table.propTypes = {
  header: PropTypes.arrayOf(PropTypes.string).isRequired,
  data: PropTypes.arrayOf(
    PropTypes.arrayOf(PropTypes.oneOfType([PropTypes.string, PropTypes.number]))
  ).isRequired,
};

export default Table;
