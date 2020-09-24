import React from 'react';
import useDarkMode from 'use-dark-mode';
import { IconButton } from "@material-ui/core";
import { Brightness4, Brightness7 } from '@material-ui/icons';

export default function DarkModeToggle() {
  const { enable, disable, value: darkMode } = useDarkMode(false);

  function handleClick() {
    if (darkMode) {
      disable();
    } else {
      enable();
    }
  }

  return (
    <IconButton color="inherit" onClick={handleClick}>
      {darkMode 
        ? <Brightness7 />
        : <Brightness4 /> }
    </IconButton>
  );
}
