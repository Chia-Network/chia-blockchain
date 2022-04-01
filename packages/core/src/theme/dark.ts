import { createTheme } from '@mui/material/styles';
import { deepmerge } from '@mui/utils';
import theme from './default';

export default createTheme(deepmerge(theme, {
  palette: {
    background: {
      default: '#212121',
      paper: '#333333',
    },
    secondary: {
      main: '#ffffff',
      contrastText: '#000000',
    },
    mode: 'dark',
  },
}));
