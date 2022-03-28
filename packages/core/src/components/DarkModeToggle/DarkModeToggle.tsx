import React from 'react';
import useDarkMode from 'use-dark-mode';
import { IconButton } from '@mui/material';
import { Brightness4, Brightness7 } from '@mui/icons-material';

export default function DarkModeToggle() {
  const { toggle, value: darkMode } = useDarkMode();

  function handleClick() {
    toggle();
  }

  return (
    <IconButton color="inherit" onClick={handleClick}>
      {darkMode ? <Brightness7 /> : <Brightness4 />}
    </IconButton>
  );
}
