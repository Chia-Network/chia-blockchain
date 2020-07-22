import React from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import Typography from "@material-ui/core/Typography";
import Container from "@material-ui/core/Container";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { useSelector, useDispatch } from "react-redux";
import myStyle from "../style";
import {
  changeEntranceMenu,
  presentSelectKeys
} from "../../modules/entranceMenu";
import {
  add_new_key_action,
  log_in_and_import_backup,
  add_and_restore_from_backup,
  login_and_skip_action
} from "../../modules/message";
import { Paper } from "@material-ui/core";

const UIPart = props => {
  var words = useSelector(state => state.mnemonic_state.mnemonic_input);
  var fingerprint = useSelector(
    state => state.wallet_state.selected_fingerprint
  );

  const dispatch = useDispatch();
  const classes = myStyle();
  if (words.length === 0) {
    words = null;
  }

  function goBack() {
    dispatch(changeEntranceMenu(presentSelectKeys));
  }

  function skip() {
    if (fingerprint !== null) {
      dispatch(login_and_skip_action(fingerprint));
    } else if (words !== null) {
      dispatch(add_new_key_action(words));
    }
  }

  const handleDragEnter = e => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragLeave = e => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDragOver = e => {
    e.preventDefault();
    e.stopPropagation();
  };
  const handleDrop = e => {
    e.preventDefault();
    e.stopPropagation();

    const file_path = e.dataTransfer.files[0].path;
    if (fingerprint !== null) {
      debugger;
      dispatch(log_in_and_import_backup(fingerprint, file_path));
    } else if (words !== null) {
      debugger;
      dispatch(add_and_restore_from_backup(words, file_path));
    }
  };

  return (
    <div className={classes.root}>
      <ArrowBackIosIcon onClick={goBack} className={classes.navigator}>
        {" "}
      </ArrowBackIosIcon>
      <div className={classes.grid_wrap}>
        <Container className={classes.grid} maxWidth="lg">
          <Typography className={classes.title} component="h4" variant="h4">
            Restore From Backup
          </Typography>
        </Container>
      </div>
      <div
        onDrop={e => handleDrop(e)}
        onDragOver={e => handleDragOver(e)}
        onDragEnter={e => handleDragEnter(e)}
        onDragLeave={e => handleDragLeave(e)}
        className={classes.dragContainer}
      >
        <Paper
          className={classes.drag}
          style={{ position: "relative", width: "80%", margin: "auto" }}
        >
          <div className={classes.dragText}>Drag and drop your backup file</div>
        </Paper>
      </div>
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Button
            onClick={skip}
            type="submit"
            fullWidth
            variant="contained"
            color="primary"
            className={classes.submit}
          >
            Skip
          </Button>
        </div>
      </Container>
    </div>
  );
};

export const RestoreBackup = () => {
  return <UIPart></UIPart>;
};
