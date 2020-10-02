import React from "react";
import Container from "@material-ui/core/Container";
import { useSelector, useDispatch } from "react-redux";
import Link from "@material-ui/core/Link";
import { useStyles } from "./selectKeyStyles";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { withRouter } from "react-router-dom";
import { changeEntranceMenu, presentSelectKeys } from "../modules/entranceMenu";
import { changeDaemonHost } from "../modules/daemon_api";

import { Button, Box, TextField } from "@material-ui/core";

export const DaemonSettings = () => {
  const dispatch = useDispatch();
  const classes = useStyles();
  var host_input = null;
  const current_host = useSelector(state => state.daemon_state.daemon_host);

  function change_daemon_host() {
    dispatch(changeDaemonHost(host_input.value));
  }

  function goBack() {
    dispatch(changeEntranceMenu(presentSelectKeys));
  }

  return (
    <div className={classes.root}>
      <Button
        onClick={goBack}
        style={{ position: "absoluite", left: 20, top: 20, color: "white" }}
      >
        <ArrowBackIosIcon> </ArrowBackIosIcon>
      </Button>
      <Container className={classes.main} component="main" maxWidth="xs">
        <div className={classes.paper}>
          <TextField
            className={classes.input}
            id="filled-secondary"
            variant="filled"
            color="secondary"
            fullWidth
            inputRef={input => {
              host_input = input;
            }}
            label="Host Name"
            value={current_host}
          />
          <Link onClick={change_daemon_host}>
            <Button
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.bottomButtonRed}
            >
              Save
            </Button>
          </Link>
        </div>
      </Container>
    </div>
  );
};
