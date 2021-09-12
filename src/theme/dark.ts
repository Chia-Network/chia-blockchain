import { createTheme } from '@material-ui/core/styles';
import theme from './default';

export default (locale: object) =>
  createTheme(
    {
      ...theme,
      palette: {
        ...theme.palette,
        secondary: {
          main: '#ffffff',
        },
        type: 'dark',
      },
    },
    locale,
  );
