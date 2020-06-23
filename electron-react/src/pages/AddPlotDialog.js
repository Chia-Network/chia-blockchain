import { openDialog } from "../modules/dialogReducer";
import DialogTitle from "@material-ui/core/DialogTitle";
import DialogContent from "@material-ui/core/DialogContent";
import DialogActions from "@material-ui/core/DialogActions";
import Dialog from "@material-ui/core/Dialog";
import isElectron from "is-electron";
import Box from "@material-ui/core/Box";
import React from "react";
import Button from "@material-ui/core/Button";
import { TextField } from "@material-ui/core";
import { useDispatch } from "react-redux";
import { makeStyles } from "@material-ui/core/styles";

const styles = theme => ({
  dialogTitle: {
    width: 500
  },
  addPlotButton: {
    width: 80,
    marginLeft: theme.spacing(2),
    height: 56
  },
  keyInput: {
    marginTop: 10
  }
});

const useStyles = makeStyles(styles);

function AddPlotDialog(props) {
  const classes = useStyles();
  const { onClose, open, ...other } = props;
  const [plotDir, setPlotDir] = React.useState("");
  const dispatch = useDispatch();

  const handleEntering = () => {};

  const handleCancel = () => {
    onClose({});
    setPlotDir("");
  };

  const handleOk = () => {
    onClose(plotDir);
    setPlotDir("");
  };

  async function select(setterFn) {
    if (isElectron()) {
      const dialogOptions = {
        properties: ["openDirectory", "showHiddenFiles"],
        buttonLabel: "Select Plot Directory"
      };
      const result = await window.remote.dialog.showOpenDialog(dialogOptions);
      const filePath = result["filePaths"][0];
      setterFn(filePath);
    } else {
      dispatch(
        openDialog("", "This feature is available only from electron app")
      );
    }
  }
  async function selectPlot() {
    select(setPlotDir);
  }

  return (
    <Dialog
      disableBackdropClick
      disableEscapeKeyDown
      maxWidth="md"
      onEntering={handleEntering}
      aria-labelledby="confirmation-dialog-title"
      open={open}
      {...other}
    >
      <DialogTitle
        id="confirmation-dialog-title"
        className={classes.dialogTitle}
      >
        Add a plot
      </DialogTitle>
      <DialogContent dividers>
        <p>
          This allows you to add a plot file that you have already created. If
          you have not created any plots, go to the plotting screen.
        </p>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              disabled
              className={classes.input}
              fullWidth
              label={plotDir === "" ? "Plot directory" : plotDir}
              variant="outlined"
            />
          </Box>
          <Box>
            <Button
              onClick={selectPlot}
              className={classes.addPlotButton}
              variant="contained"
              color="primary"
            >
              Select
            </Button>
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button autoFocus onClick={handleCancel} color="secondary">
          Cancel
        </Button>
        <Button onClick={handleOk} color="secondary">
          Ok
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default AddPlotDialog;
