import React from 'react';
import { makeStyles, Theme, createStyles } from '@material-ui/core/styles';

const useStyles = makeStyles((theme: Theme) =>
  createStyles({
    toolbar: theme.mixins.toolbar,
  }),
);

export default function ToolbarSpacing() {
  const classes = useStyles();

  return <div className={classes.toolbar} />;
}
