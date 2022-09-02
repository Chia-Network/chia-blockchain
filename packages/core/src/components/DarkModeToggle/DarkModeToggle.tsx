import React from 'react';
import { IconButton } from '@mui/material';
import { Brightness4, Brightness7 } from '@mui/icons-material';
import useDarkMode from '../../hooks/useDarkMode';
import isElectron from 'is-electron';
import { nativeTheme } from '@electron/remote';

export default function DarkModeToggle() {
  const { toggle, isDarkMode } = useDarkMode();

  function handleClick() {
    toggle();
    if (isElectron()) {
      nativeTheme.themeSource = isDarkMode ? 'dark' : 'light';
    }
  }

  return (
    <IconButton color="inherit" onClick={handleClick}>
      {isDarkMode ? <Brightness7 /> : <Brightness4 />}
    </IconButton>
  );
}
