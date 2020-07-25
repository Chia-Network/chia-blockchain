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
    marginTop: theme.spacing(2),
    padding: theme.spacing(2)
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

const Connections = props => {
  const classes = useStyles();

  const connections = props.connections;
  const connectionError = props.connectionError;
  const connectionTime = props.connectionTime ? props.connectionTime : false;

  const [host, setHost] = React.useState("");
  const handleChangeHost = event => {
    setHost(event.target.value);
  };

  const [port, setPort] = React.useState("");
  const handleChangePort = event => {
    setPort(event.target.value);
  };

  const deleteConnection = node_id => {
    return () => {
      props.closeConnection(node_id);
    };
  };
  const connectToPeer = () => {
    props.openConnection(host, port);
    setHost("");
    setPort("");
  };

  return (
    <Paper className={classes.balancePaper}>
      <Grid container spacing={0}>
        <Grid item xs={12}>
          <div className={classes.cardTitle}>
            <Typography component="h6" variant="h6">
              Connections
            </Typography>
          </div>
          <TableContainer component={Paper}>
            <Table
              className={classes.table}
              size="small"
              aria-label="a dense table"
            >
              <TableHead>
                <TableRow>
                  <TableCell>Node Id</TableCell>
                  <TableCell align="right">Ip address</TableCell>
                  <TableCell align="right">Port</TableCell>
                  <TableCell align="right">Up/Down</TableCell>
                  <TableCell align="right">Connection type</TableCell>
                  {connectionTime ? (
                    <TableCell align="right">Connected</TableCell>
                  ) : null}
                  {connectionTime ? (
                    <TableCell align="right">Last message</TableCell>
                  ) : null}
                  <TableCell align="right">Delete</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {connections.map(item => (
                  <TableRow key={item.node_id}>
                    <TableCell component="th" scope="row">
                      {item.node_id.substring(0, 10)}...
                    </TableCell>
                    <TableCell align="right">{item.peer_host}</TableCell>
                    <TableCell align="right">
                      {item.peer_port}/{item.peer_server_port}
                    </TableCell>

                    <TableCell align="right">
                      {Math.floor(item.bytes_written / 1024)}/
                      {Math.floor(item.bytes_read / 1024)} KiB
                    </TableCell>
                    <TableCell align="right">
                      {service_connection_types[item.type]}
                    </TableCell>

                    {connectionTime ? (
                      <TableCell align="right">
                        {unix_to_short_date(parseInt(item.creation_time))}
                      </TableCell>
                    ) : null}
                    {connectionTime ? (
                      <TableCell align="right">
                        {unix_to_short_date(parseInt(item.last_message_time))}
                      </TableCell>
                    ) : null}
                    <TableCell
                      className={classes.clickable}
                      onClick={deleteConnection(item.node_id)}
                      align="right"
                    >
                      <DeleteForeverIcon></DeleteForeverIcon>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <h4 className={classes.connect}>Connect to other peers</h4>
          <form className={classes.form} noValidate autoComplete="off">
            <TextField
              label="Ip address / host"
              value={host}
              onChange={handleChangeHost}
            />
            <TextField label="Port" value={port} onChange={handleChangePort} />
            <Button
              variant="contained"
              color="primary"
              onClick={connectToPeer}
              className={classes.button}
              startIcon={<SettingsInputAntennaIcon />}
            >
              Connect
            </Button>
          </form>
          {connectionError === "" ? (
            ""
          ) : (
            <p className={classes.error}>{connectionError}</p>
          )}
        </Grid>
      </Grid>
    </Paper>
  );
};

export default Connections;
