import { withStyles } from '@material-ui/styles';
import TextField from '@material-ui/core/TextField';

const CssTextField = withStyles({
  root: {
    '& .MuiFormLabel-root': {
      color: '#e3f2fd',
    },
    '& MuiInputLabel-root': {
      color: '#e3f2fd',
    },
    '& label.Mui-focused': {
      color: '#e3f2fd',
    },
    '& label.Mui-required': {
      color: '#e3f2fd',
    },
    '& label.Mui-disabled': {
      color: '#e3f2fd',
    },
    '& label.Mui-root': {
      color: '#e3f2fd',
    },
    '& .MuiInput-underline:after': {
      borderBottomColor: '#e3f2fd',
    },
    '& .MuiOutlinedInput-root': {
      '& fieldset': {
        borderColor: '#e3f2fd',
      },
      '&:hover fieldset': {
        borderColor: '#e3f2fd',
      },
      '&.Mui-focused fieldset': {
        borderColor: '#e3f2fd',
      },
      '&.Mui-disabled fieldset': {
        borderColor: '#e3f2fd',
      },
    },
    color: '#ffffff',
    '& .MuiOutlinedInput-input': {
      color: '#ffffff',
    },
  },
})(TextField);

export default CssTextField;
