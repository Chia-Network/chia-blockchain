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
  login_and_skip_action,
  get_backup_info_action
} from "../../modules/message";
import { Paper, Grid } from "@material-ui/core";
import {
  changeBackupView,
  presentMain,
  presentBackupInfo
} from "../../modules/backup_state";
import { unix_to_short_date } from "../../util/utils";
import { Box } from "@material-ui/core";

const UIPart = props => {
  const dispatch = useDispatch();
  const classes = myStyle();
  var words = useSelector(state => state.mnemonic_state.mnemonic_input);
  var fingerprint = useSelector(
    state => state.wallet_state.selected_fingerprint
  );

  for (let word of words) {
    if (word === "") {
      words = null;
    }
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
    debugger;
    if (fingerprint !== null) {
      dispatch(get_backup_info_action(file_path, fingerprint, null));
    } else if (words !== null) {
      dispatch(get_backup_info_action(file_path, null, words));
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
            Restore Smart Wallets From Backup
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

const BackupDetails = () => {
  const classes = myStyle();
  const dispatch = useDispatch();
  const file_path = useSelector(state => state.backup_state.selected_file_path);
  const backup_info = useSelector(state => state.backup_state.backup_info);
  const date = unix_to_short_date(backup_info["timestamp"]);
  const backup_fingerprint = backup_info["fingerprint"];
  const version = backup_info["version"];
  const wallets = backup_info["wallets"];

  var words = useSelector(state => state.mnemonic_state.mnemonic_input);
  var fingerprint = useSelector(
    state => state.wallet_state.selected_fingerprint
  );

  for (let word of words) {
    if (word === "") {
      words = null;
    }
  }

  function goBack() {
    dispatch(changeBackupView(presentMain));
    dispatch(changeEntranceMenu(presentSelectKeys));
  }

  function next() {
    if (fingerprint !== null) {
      dispatch(log_in_and_import_backup(fingerprint, file_path));
    } else if (words !== null) {
      dispatch(add_and_restore_from_backup(words, file_path));
    }
  }

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
      <div className={classes.dragContainer}>
        <Paper
          className={classes.drag}
          style={{
            position: "relative",
            width: "80%",
            margin: "auto",
            padding: "20px"
          }}
        >
          <Grid container spacing={0} style={{ marginBottom: 10 }}>
            <Grid item xs={6}>
              <Typography variant="subtitle1">Backup info:</Typography>
              <Box display="flex" style={{ minWidth: "100%" }}>
                <Box flexGrow={1}>Date: </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {date}
                </Box>
              </Box>
              <Box display="flex" style={{ minWidth: "100%" }}>
                <Box flexGrow={1}>Version: </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {version}
                </Box>
              </Box>
              <Box display="flex" style={{ minWidth: "100%" }}>
                <Box flexGrow={1}>Fingerprint: </Box>
                <Box className={classes.align_right} flexGrow={1}>
                  {backup_fingerprint}
                </Box>
              </Box>
            </Grid>
          </Grid>
          <Typography variant="subtitle1">Smart wallets</Typography>
          <WalletHeader></WalletHeader>
          {wallets.map(wallet => (
            <WalletRow wallet={wallet}></WalletRow>
          ))}
        </Paper>
      </div>
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Button
            onClick={next}
            type="submit"
            fullWidth
            variant="contained"
            color="primary"
            className={classes.submit}
          >
            Continue
          </Button>
        </div>
      </Container>
    </div>
  );
};

const WalletRow = props => {
  const wallet = props.wallet;
  const id = wallet.id;
  const name = wallet.name;
  const type = wallet.type_name;
  const classes = myStyle();

  return (
    <Box display="flex" style={{ minWidth: "100%" }}>
      <Box className={classes.column_three} flexGrow={1}>
        {id}
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_center}> {name}</div>
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_right}> {type}</div>
      </Box>
    </Box>
  );
};

const WalletHeader = () => {
  const classes = myStyle();

  return (
    <Box display="flex" style={{ minWidth: "100%" }}>
      <Box className={classes.column_three} flexGrow={1}>
        <Typography variant="subtitle2"> id</Typography>
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_center}>
          {" "}
          <Typography variant="subtitle2"> name</Typography>
        </div>
      </Box>
      <Box className={classes.column_three} flexGrow={1}>
        <div className={classes.align_right}>
          {" "}
          <Typography variant="subtitle2"> type</Typography>
        </div>
      </Box>
    </Box>
  );
};

export const RestoreBackup = () => {
  const view = useSelector(state => state.backup_state.view);
  if (view === presentBackupInfo) {
    return <BackupDetails></BackupDetails>;
  } else {
    return <UIPart></UIPart>;
  }
};
