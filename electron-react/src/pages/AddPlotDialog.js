import { openDialog } from "../modules/dialogReducer";
import DialogTitle from "@material-ui/core/DialogTitle";
import DialogContent from "@material-ui/core/DialogContent";
import DialogActions from "@material-ui/core/DialogActions";
import Dialog from "@material-ui/core/Dialog";
import isElectron from "is-electron";
import Box from "@material-ui/core/Box";
import React from "react";
import Button from "@material-ui/core/Button";
import List from "@material-ui/core/List";
import ListItem from "@material-ui/core/ListItem";
import ListItemAvatar from "@material-ui/core/ListItemAvatar";
import ListItemSecondaryAction from "@material-ui/core/ListItemSecondaryAction";
import ListItemText from "@material-ui/core/ListItemText";
import Avatar from "@material-ui/core/Avatar";
import IconButton from "@material-ui/core/IconButton";
import FolderIcon from "@material-ui/icons/Folder";
import DeleteIcon from "@material-ui/icons/Delete";
import { useSelector, useDispatch } from "react-redux";
import { makeStyles } from "@material-ui/core/styles";

import {
  add_plot_directory_and_refresh,
  remove_plot_directory_and_refresh
} from "../modules/message";

const styles = theme => ({
  dialogTitle: {
    width: 500
  },
  addPlotButton: {
    width: 220,
    marginLeft: theme.spacing(2),
    height: 56
  },
  keyInput: {
    marginTop: 10
  },
  dirList: {
    width: "100%"
  }
});

const useStyles = makeStyles(styles);

function AddPlotDialog(props) {
  const classes = useStyles();
  const { onClose, open, ...other } = props;
  const dispatch = useDispatch();

  const directories = useSelector(
    state => state.farming_state.harvester.plot_directories
  );

  const removePlotDir = dir => {
    dispatch(remove_plot_directory_and_refresh(dir));
  };

  async function select() {
    if (isElectron()) {
      const dialogOptions = {
        properties: ["openDirectory", "showHiddenFiles"],
        buttonLabel: "Select Plot Directory"
      };
      const result = await window.remote.dialog.showOpenDialog(dialogOptions);
      console.log(result);
      if (!result.canceled) {
        const filePath = result["filePaths"][0];
        dispatch(add_plot_directory_and_refresh(filePath));
      }
    } else {
      dispatch(
        openDialog("", "This feature is available only from electron app")
      );
    }
  }

  return (
    <Dialog
      disableBackdropClick
      disableEscapeKeyDown
      maxWidth="md"
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
          This allows you to add a directory that has plots in it. If you have
          not created any plots, go to the plotting screen.
        </p>
        <Box display="flex">
          <List dense={true} className={classes.dirList}>
            {directories.map(dir => (
              <ListItem>
                <ListItemAvatar>
                  <Avatar>
                    <FolderIcon />
                  </Avatar>
                </ListItemAvatar>
                <ListItemText primary={dir} />
                <ListItemSecondaryAction>
                  <IconButton
                    edge="end"
                    aria-label="delete"
                    onClick={() => removePlotDir(dir)}
                  >
                    <DeleteIcon />
                  </IconButton>
                </ListItemSecondaryAction>
              </ListItem>
            ))}
          </List>
        </Box>
        <Box display="flex">
          <Box>
            <Button
              onClick={select}
              className={classes.addPlotButton}
              variant="contained"
              color="primary"
            >
              Add plot directory
            </Button>
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button autoFocus onClick={onClose} color="secondary">
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default AddPlotDialog;
