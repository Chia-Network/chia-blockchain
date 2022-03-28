import { createTheme } from '@mui/material/styles';
import { deepmerge } from '@mui/utils';
import theme from './default';

export default createTheme(deepmerge(theme, {
  palette: {
    background: {
      default: '#121212',
    },
    secondary: {
      main: '#ffffff',
    },
    mode: 'dark',
  },
}));
