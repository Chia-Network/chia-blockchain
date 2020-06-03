import React from "react";
import ListItem from "@material-ui/core/ListItem";
import ListItemIcon from "@material-ui/core/ListItemIcon";
import ListItemText from "@material-ui/core/ListItemText";
import {
  presentWallet,
  presentNode,
  presentFarmer,
  changeMainMenu
} from "../modules/mainMenu";
import { delete_all_keys, logOut } from "../modules/message";
import { useDispatch } from "react-redux";
import List from "@material-ui/core/List";
import Divider from "@material-ui/core/Divider";
import AccountBalanceWalletIcon from "@material-ui/icons/AccountBalanceWallet";
import AccountTreeIcon from "@material-ui/icons/AccountTree";
import DonutLargeIcon from "@material-ui/icons/DonutLarge";
import LockIcon from "@material-ui/icons/Lock";
import DeleteForeverIcon from "@material-ui/icons/DeleteForever";
import Button from "@material-ui/core/Button";
import Dialog from "@material-ui/core/Dialog";
import DialogActions from "@material-ui/core/DialogActions";
import DialogContent from "@material-ui/core/DialogContent";
import DialogContentText from "@material-ui/core/DialogContentText";
import DialogTitle from "@material-ui/core/DialogTitle";
import { changeEntranceMenu, presentSelectKeys } from "../modules/entranceMenu";

const menuItems = [
  {
    label: "Wallet",
    present: presentWallet,
    icon: <AccountBalanceWalletIcon></AccountBalanceWalletIcon>
  },
  {
    label: "Full Node",
    present: presentNode,
    icon: <AccountTreeIcon></AccountTreeIcon>
  },
  {
    label: "Farming",
    present: presentFarmer,
    icon: <DonutLargeIcon></DonutLargeIcon>
  }
];

const MenuItem = menuItem => {
  const dispatch = useDispatch();
  const item = menuItem;

  function presentMe() {
    dispatch(changeMainMenu(item.present));
  }

  return (
    <ListItem button onClick={presentMe} key={item.label}>
      <ListItemIcon>{item.icon}</ListItemIcon>
      <ListItemText primary={item.label} />
    </ListItem>
  );
};

export const SideBar = () => {
  const [open, setOpen] = React.useState(false);
  const dispatch = useDispatch();

  const handleClickOpen = () => {
    setOpen(true);
  };

  const handleClose = () => {
    setOpen(false);
  };

  const handleCloseDelete = () => {
    handleClose();
    dispatch(delete_all_keys());
  };

  function changeKey() {
    // console.log("Changing key");
    dispatch(logOut("log_out", {}));
    dispatch(changeEntranceMenu(presentSelectKeys));
  }

  return (
    <div>
      <List>{menuItems.map(item => MenuItem(item))}</List>
      <Divider />
      <List>
        <div>
          <ListItem button onClick={handleClickOpen} key="0">
            <ListItemIcon>
              <DeleteForeverIcon />
            </ListItemIcon>
            <ListItemText primary="Delete All Keys" />
          </ListItem>
          <ListItem button onClick={changeKey} key="1">
            <ListItemIcon>
              <LockIcon />
            </ListItemIcon>
            <ListItemText primary="Change Key" />
          </ListItem>
        </div>
      </List>
      <Dialog
        open={open}
        onClose={handleClose}
        aria-labelledby="alert-dialog-title"
        aria-describedby="alert-dialog-description"
      >
        <DialogTitle id="alert-dialog-title">{"Delete all keys"}</DialogTitle>
        <DialogContent>
          <DialogContentText id="alert-dialog-description">
            Deleting all keys will permanatly remove the keys from your
            computer, make sure you have backups. Are you sure you want to
            continue?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} color="secondary">
            Back
          </Button>
          <Button onClick={handleCloseDelete} color="secondary" autoFocus>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};
