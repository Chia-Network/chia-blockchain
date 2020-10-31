import React from "react";
import { makeStyles } from "@material-ui/core/styles";
import Modal from "@material-ui/core/Modal";
import { Button } from "@material-ui/core";
import { useSelector, useDispatch } from "react-redux";
import { showCreateBackup, create_backup_action } from "../../modules/message";
import isElectron from "is-electron";
import { openDialog } from "../../modules/dialog";

function getModalStyle() {
  const top = 50;
  const left = 50;

  return {
    top: `${top}%`,
    left: `${left}%`,
    transform: `translate(-${top}%, -${left}%)`
  };
}

const useStyles = makeStyles(theme => ({
  paper: {
    position: "absolute",
    width: 400,
    backgroundColor: theme.palette.background.paper,
    border: "1px solid #000",
    borderRadius: "5px",
    boxShadow: theme.shadows[5],
    padding: theme.spacing(2, 4, 3)
  }
}));

export const CreateBackup = () => {
  const show_create_backup = useSelector(
    state => state.wallet_state.show_create_backup
  );
  const dispatch = useDispatch();
  function handleClose() {
    console.log("Modal dialog closed");
    dispatch(showCreateBackup(false));
  }

  async function create_backup() {
    if (isElectron()) {
      const dialogOptions = {};
      const result = await window.remote.dialog.showSaveDialog(dialogOptions);
      const { filePath } = result;
      dispatch(create_backup_action(filePath));
    } else {
      dispatch(
        openDialog("", "This feature is available only from electron app")
      );
    }
  }

  const classes = useStyles();

  const modalStyle = getModalStyle();
  const body = (
    <div style={modalStyle} className={classes.paper}>
      <h2 id="simple-modal-title">Create a Backup</h2>
      <p id="simple-modal-description">
        Backup file is used to restore smart wallets.
      </p>
      <Button
        style={{
          float: "right",
          width: "100px",
          height: "45px",
          backgroundColor: "#0000dd",
          color: "white"
        }}
        onClick={create_backup}
      >
        Create
      </Button>
    </div>
  );
  return (
    <Modal
      open={show_create_backup}
      onClose={handleClose}
      aria-labelledby="simple-modal-title"
      aria-describedby="simple-modal-description"
    >
      {body}
    </Modal>
  );
};
