import React, { Component } from "react";
import Grid from "@material-ui/core/Grid";
import { withStyles } from "@material-ui/core/styles";
import Typography from "@material-ui/core/Typography";
import { Paper, TableRow, Tooltip } from "@material-ui/core";
import Button from "@material-ui/core/Button";
import Table from "@material-ui/core/Table";
import TableBody from "@material-ui/core/TableBody";
import TableCell from "@material-ui/core/TableCell";
import TableContainer from "@material-ui/core/TableContainer";
import { unix_to_short_date } from "../util/utils";
import { clearBlock, getHeader, getBlock } from "../modules/fullnodeMessages";
import { connect } from "react-redux";
import { chia_formatter } from "../util/chia";
import { hex_to_array, arr_to_hex, sha256 } from "../util/utils";
import { hash_header } from "../util/header";
import HelpIcon from "@material-ui/icons/Help";

/* global BigInt */

const styles = theme => ({
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
});

class Block extends Component {
  constructor(props) {
    super(props);
    this.state = {
      headerHash: "",
      plotSeed: ""
    };
  }

  async fetchHeaderIfNecessary() {
    if (this.props.prevHeader) {
      const phh = await hash_header(this.props.prevHeader);
      if (phh !== this.props.block.header.data.prev_header_hash) {
        this.props.getHeader(this.props.block.header.data.prev_header_hash);
      }
    } else {
      this.props.getHeader(this.props.block.header.data.prev_header_hash);
    }
    const headerHash = await hash_header(this.props.block.header);

    let buf = hex_to_array(this.props.block.proof_of_space.pool_public_key);
    buf = buf.concat(
      hex_to_array(this.props.block.proof_of_space.plot_public_key)
    );
    const bufHash = await sha256(buf);
    const plotSeed = arr_to_hex(bufHash);
    this.setState({
      headerHash,
      plotSeed
    });
  }

  async componentDidMount(prevProps) {
    await this.fetchHeaderIfNecessary();
  }

  async componentDidUpdate(prevProps) {
    if (
      this.props.block.header.data.prev_header_hash !==
        prevProps.block.header.data.prev_header_hash &&
      this.props.block.header.data.height > 0
    ) {
      await this.fetchHeaderIfNecessary();
    }
  }

  render() {
    const classes = this.props.classes;

    const block = this.props.block;
    const prevHeader = this.props.prevHeader;

    let diff = 0;
    if (block.header.data.height === 0) {
      diff = block.header.data.weight;
    } else if (prevHeader) {
      diff = block.header.data.weight - prevHeader.data.weight;
    }
    const headerHash = "0x" + this.state.headerHash;
    const plotSeed = "0x" + this.state.plotSeed;
    const chia_cb = chia_formatter(
      parseFloat(BigInt(block.header.data.coinbase.amount)),
      "mojo"
    )
      .to("chia")
      .toString();
    const chia_fees = chia_formatter(
      parseFloat(BigInt(block.header.data.fees_coin.amount)),
      "mojo"
    )
      .to("chia")
      .toString();

    const rows = [
      { name: "Header hash", value: headerHash },
      {
        name: "Timestamp",
        value: unix_to_short_date(block.header.data.timestamp),
        tooltip:
          "This is the time the block was created by the farmer, which is before it is finalized with a proof of time"
      },
      { name: "Height", value: block.header.data.height },
      {
        name: "Weight",
        value: BigInt(block.header.data.weight).toLocaleString(),
        tooltip:
          "Weight is the total added difficulty of all blocks up to and including this one"
      },
      { name: "Previous block", value: block.header.data.prev_header_hash },
      { name: "Difficulty", value: BigInt(diff).toLocaleString() },
      {
        name: "Total VDF Iterations",
        value: BigInt(block.header.data.total_iters).toLocaleString(),
        tooltip:
          "The total number of VDF (verifiable delay function) or proof of time iterations on the whole chain up to this block."
      },
      {
        name: "Block VDF Iterations",
        value: BigInt(
          block.proof_of_time.number_of_iterations
        ).toLocaleString(),
        tooltip:
          "The total number of VDF (verifiable delay function) or proof of time iterations on this block."
      },
      { name: "Proof of Space Size", value: block.proof_of_space.size },
      { name: "Plot Public Key", value: block.proof_of_space.plot_public_key },
      { name: "Pool Public Key", value: block.proof_of_space.pool_public_key },
      {
        name: "Plot Seed",
        value: plotSeed,
        tooltip:
          "The seed used to create the plot, this depends on the pool pk and plot pk"
      },
      {
        name: "Transactions Filter Hash",
        value: block.header.data.filter_hash
      },
      {
        name: "Transactions Generator Hash",
        value: block.header.data.generator_hash
      },
      {
        name: "Coinbase Amount",
        value: chia_cb + " TXCH",
        tooltip:
          "The Chia block reward, goes to the pool (or individual farmer)"
      },
      {
        name: "Coinbase Puzzle Hash",
        value: block.header.data.coinbase.puzzle_hash
      },
      {
        name: "Fees Amount",
        value: chia_fees + " TXCH",
        tooltip: "The total fees in this block, goes to the farmer"
      },
      {
        name: "Fees Puzzle Hash",
        value: block.header.data.fees_coin.puzzle_hash
      }
    ];
    return (
      <Paper className={classes.balancePaper}>
        <Grid container spacing={0}>
          <Grid item xs={12}>
            <Button onClick={this.props.clearBlock}>Back</Button>
            <div className={classes.cardTitle}>
              <Typography component="h6" variant="h6">
                Block at height {block.header.data.height} in the Chia
                blockchain
              </Typography>
            </div>
            <TableContainer component={Paper}>
              <Table className={classes.table} aria-label="simple table">
                <TableBody>
                  {rows.map(row => (
                    <TableRow key={row.name}>
                      <TableCell component="th" scope="row">
                        {row.name}{" "}
                        {row.tooltip ? (
                          <Tooltip title={row.tooltip}>
                            <HelpIcon
                              style={{ color: "#c8c8c8", fontSize: 12 }}
                            ></HelpIcon>
                          </Tooltip>
                        ) : (
                          ""
                        )}
                      </TableCell>
                      <TableCell
                        onClick={
                          row.name === "Previous block"
                            ? () => this.props.getBlock(row.value)
                            : () => {}
                        }
                        align="right"
                      >
                        {row.value}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>
        </Grid>
      </Paper>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  return {};
};

const mapDispatchToProps = (dispatch, ownProps) => {
  return {
    clearBlock: () => {
      dispatch(clearBlock());
    },
    getHeader: headerHash => {
      dispatch(getHeader(headerHash));
    },
    getBlock: headerHash => {
      dispatch(getBlock(headerHash));
    }
  };
};
export default connect(
  mapStateToProps,
  mapDispatchToProps
)(withStyles(styles)(Block));
