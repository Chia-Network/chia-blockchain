import React from 'react';
import ListItem from '@material-ui/core/ListItem';
import ListItemIcon from '@material-ui/core/ListItemIcon';
import ListItemText from '@material-ui/core/ListItemText';
import DashboardIcon from '@material-ui/icons/Dashboard';
import AssignmentIcon from '@material-ui/icons/Assignment';
import {
    presentWallet, presentNode,
    presentFarmer, presentTimelord,
    changeMainMenu
} from '../modules/mainMenu'
import { log_out } from '../modules/message';
import { useDispatch, useSelector } from 'react-redux';
import List from '@material-ui/core/List';
import Divider from '@material-ui/core/Divider';
import AccountBalanceWalletIcon from '@material-ui/icons/AccountBalanceWallet';
import AccountTreeIcon from '@material-ui/icons/AccountTree';
import DonutLargeIcon from '@material-ui/icons/DonutLarge';
import UpdateIcon from '@material-ui/icons/Update';
import LockIcon from '@material-ui/icons/Lock';

const menuItems = [
    {
        label: "Wallet",
        present: presentWallet,
        icon: <AccountBalanceWalletIcon></AccountBalanceWalletIcon>
    },
    {
        label: "Node",
        present: presentNode,
        icon: <AccountTreeIcon></AccountTreeIcon>
    },
    {
        label: "Farmer",
        present: presentFarmer,
        icon: <DonutLargeIcon></DonutLargeIcon>
    },
    {
        label: "Timelord",
        present: presentTimelord,
        icon: <UpdateIcon></UpdateIcon>
    },
]

const MenuItem= (menuItem) => {

    const dispatch = useDispatch()
    const item = menuItem

    function presentMe() {
        dispatch(changeMainMenu(item.present))
    }

    return (
        <ListItem button onClick={presentMe}>
            <ListItemIcon>
                {item.icon}
            </ListItemIcon>
            <ListItemText primary={item.label} />
        </ListItem>
    )
}

export const SideBar = () => {

    const dispatch = useDispatch()

    function logOut() {
        console.log("Logging out")
        dispatch(log_out())
    }

    return (
        <div>
            <List>
                {menuItems.map(item => (MenuItem(item)))}
            </List>
            <Divider />
            <List>
                <div>
                    <ListItem button onClick={logOut}>
                        <ListItemIcon>
                            <LockIcon />
                        </ListItemIcon>
                        <ListItemText primary="Log Out" />
                    </ListItem>
                </div>
            </List>
        </div>
    )
}