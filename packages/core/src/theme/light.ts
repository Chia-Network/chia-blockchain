import { createTheme } from '@material-ui/core/styles';
import theme from './default';

export default createTheme({
  ...theme,
  palette: {
    ...theme.palette,
  },
});
