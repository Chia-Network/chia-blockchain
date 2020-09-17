import React from "react";
import Button from "@material-ui/core/Button";
import Dialog from "@material-ui/core/Dialog";
import DialogActions from "@material-ui/core/DialogActions";
import DialogContent from "@material-ui/core/DialogContent";
import DialogContentText from "@material-ui/core/DialogContentText";
import DialogTitle from "@material-ui/core/DialogTitle";
import { closeDialog } from "../modules/dialogReducer";
import { useDispatch, useSelector } from "react-redux";
import { Backdrop } from "@material-ui/core";
import { CircularProgress } from "@material-ui/core";
import { useStyles } from "./CreateWallet";

export const DialogItem = props => {
  const dialog = props.dialog;
  const text = dialog.label;
  const title = dialog.title;
  const id = dialog.id;
  const dispatch = useDispatch();
  const open = true;

  const handleClose = () => {
    dispatch(closeDialog(id));
  };
  return (
    <div>
      <Dialog
        open={open}
        onClose={handleClose}
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
      >
        <DialogTitle id="alert-dialog-title">{title}</DialogTitle>
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            {text}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} color="secondary" autoFocus>
            Ok
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export const ModalDialog = () => {
  const dialogs = useSelector(state => state.dialog_state.dialogs);

  return (
    <div>
      {dialogs.map(dialog => (
        <DialogItem dialog={dialog} key={dialog.id}></DialogItem>
      ))}
    </div>
  );
};

export const Spinner = () => {
  const show = useSelector(state => state.progress.progress_indicator);
  const classes = useStyles();
  return (
    <Backdrop className={classes.backdrop} open={show}>
      <CircularProgress color="inherit" />
    </Backdrop>
  );
};
