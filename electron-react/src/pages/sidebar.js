import React from 'react';
import ListItem from '@material-ui/core/ListItem';
import ListItemIcon from '@material-ui/core/ListItemIcon';
import ListItemText from '@material-ui/core/ListItemText';
import DashboardIcon from '@material-ui/icons/Dashboard';
import AssignmentIcon from '@material-ui/icons/Assignment';
import {
    presentWallet, presentNode,
    presentFarmer, presentTimelord,
    changeView
} from '../modules/presenter'
import { log_out } from '../modules/message';
import { useDispatch, useSelector } from 'react-redux';
import List from '@material-ui/core/List';
import Divider from '@material-ui/core/Divider';


const menuItems = [
    {
        label: "Wallet",
        present: presentWallet
    },
    {
        label: "Node",
        present: presentNode
    },
    {
        label: "Farmer",
        present: presentFarmer
    },
    {
        label: "Timelord",
        present: presentTimelord
    },
]

const MenuItem= (menuItem) => {

    const dispatch = useDispatch()
    const item = menuItem

    function presentMe() {
        dispatch(changeView("main_menu", item.present))
    }

    return (
        <ListItem button onClick={presentMe}>
            <ListItemIcon>
                <DashboardIcon />
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
                            <AssignmentIcon />
                        </ListItemIcon>
                        <ListItemText primary="Log Out" />
                    </ListItem>
                </div>
            </List>
        </div>
    )
}