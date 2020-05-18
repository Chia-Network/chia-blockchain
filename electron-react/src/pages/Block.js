import React from "react";
import Grid from "@material-ui/core/Grid";
import { makeStyles } from "@material-ui/core/styles";
import Typography from "@material-ui/core/Typography";
import { Paper, TableRow } from "@material-ui/core";
import Button from "@material-ui/core/Button";
import Table from "@material-ui/core/Table";
import TableBody from "@material-ui/core/TableBody";
import TableCell from "@material-ui/core/TableCell";
import TableContainer from "@material-ui/core/TableContainer";
import TableHead from "@material-ui/core/TableHead";
import DeleteForeverIcon from "@material-ui/icons/DeleteForever";
import { unix_to_short_date } from "../util/utils";
import { service_connection_types } from "../util/service_names";
import TextField from "@material-ui/core/TextField";
import SettingsInputAntennaIcon from "@material-ui/icons/SettingsInputAntenna";
import { clearBlock } from "../modules/fullnodeMessages";
import { connect, useSelector, useDispatch } from "react-redux";
import {chia_formatter} from "../util/chia";

/* global BigInt */

const useStyles = makeStyles(theme => ({
  form: {
    margin: theme.spacing(1)
  },
  clickable: {
    cursor: "pointer"
  },
  error: {
    color: "red"
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0)
  },
  balancePaper: {
    marginTop: theme.spacing(2)
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1)
  },
  table: {
    minWidth: 650
  },
  connect: {
    marginLeft: theme.spacing(1)
  }
}));


const Block = props => {
  const classes = useStyles();
  const dispatch = useDispatch();

  function back() {
    dispatch(clearBlock());
  }

  const block = props.block;
  const prevHeader = props.prevHeader;

  let diff = 0;
  if (block.header.data.height == 0) {
      diff = block.header.data.weight;
  } else if (prevHeader) {
      diff = block.header.data.weight - prevHeader.data.weight;
  }
  const headerHash = "0x" + props.headerHash;
  const chia_cb = chia_formatter(parseFloat(BigInt(block.header.data.coinbase.amount)), 'mojo').to('chia').toString();
  const chia_fees = chia_formatter(parseFloat(BigInt(block.header.data.fees_coin.amount)), 'mojo').to('chia').toString();
  const rows = [
      {"name": "Header hash", "value": headerHash},
      {"name": "Timestamp", "value": unix_to_short_date(block.header.data.timestamp)},
      {"name": "Height", "value": block.header.data.height},
      {"name": "Weight", "value": BigInt(block.header.data.weight).toLocaleString()},
      {"name": "Previous block", "value": block.header.data.prev_header_hash},
      {"name": "Difficulty", "value": BigInt(diff).toLocaleString()},
      {"name": "Total VDF Iterations", "value": BigInt(block.header.data.total_iters).toLocaleString()},
      {"name": "Block VDF Iterations", "value": BigInt(block.proof_of_time.number_of_iterations).toLocaleString()},
      {"name": "Proof of Space Size", "value": block.proof_of_space.size},
      {"name": "Plot Public Key", "value": block.proof_of_space.plot_pubkey},
      {"name": "Pool Public Key", "value": block.proof_of_space.pool_pubkey},
      {"name": "Transactions Filter Hash", "value": block.header.data.filter_hash},
      {"name": "Transactions Generator Hash", "value": block.header.data.generator_hash},
      {"name": "Coinbase Amount", "value": chia_cb + " XCH"},
      {"name": "Coinbase Puzzle Hash", "value": block.header.data.coinbase.puzzle_hash},
      {"name": "Fees Amount", "value": chia_fees + " XCH"},
      {"name": "Fees Puzzle Hash", "value": block.header.data.fees_coin.puzzle_hash},
  ]
  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
            <Button onClick={back}>Back</Button>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Block at height {block.header.data.height} in the Chia blockchain
            </Typography>
          </div>
          <TableContainer component={Paper}>
          <Table className={classes.table} aria-label="simple table">
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.name}>
                  <TableCell component="th" scope="row">
                    {row.name}
                  </TableCell>
                  <TableCell align="right">{row.value}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        </Grid>
      </Grid>
    </Paper>
  );
};

export default Block;