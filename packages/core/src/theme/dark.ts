import { createTheme } from '@mui/material/styles';
import theme from './default';

export default createTheme({
  ...theme,
  palette: {
    ...theme.palette,
    background: {
      ...theme.palette.background,
      default: '#212121',
      paper: '#333333',
      card: 'rgba(255, 255, 255, 0.08)',
    },
    secondary: {
      ...theme.palette.secondary,
      main: '#ffffff',
      contrastText: '#000000',
    },
    mode: 'dark',
  },
});
