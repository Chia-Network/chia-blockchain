declare module '@mui/material' {
  interface Color {
    main: string;
    dark: string;
  }
}

export default {
  palette: {
    background: {
      default: '#fafafa',
    },
    primary: {
      main: '#3AAC59', // '#00C853',
      contrastText: '#ffffff',
    },
    secondary: {
      main: '#000000',
      contrastText: '#ffffff',
    },
    danger: {
      main: '#dc3545',
      contrastText: '#ffffff',
    },
    highlight: {
      main: '#00C853',
    },
    border: {
      main: '#E0E0E0',
      dark: '#484747',
    },
    sidebarBackground: {
      main: '#E8F5E9',
      dark: '#505C4E',
    },
    sidebarIconSelected: {
      main: '#1B5E20',
      dark: '#3AAC59',
    },
    sidebarIcon: {
      main: '#9E9E9E',
      dark: '#9E9E9E',
    },
    sidebarIconHover: {
      main: '#424242',
      dark: 'white',
    },
  },
  drawer: {
    width: '72px',
  },
  mixins: {
    toolbar: {
      minHeight: '90px',
    },
  },
  components: {
    MuiSvgIcon: {
      variants: [
        {
          props: { fontSize: 'extraLarge' },
          style: {
            fontSize: '3rem',
          },
        },
        {
          props: { fontSize: 'sidebarIcon' },
          style: {
            fontSize: '2rem',
          },
        },
      ],
    },
    MuiTypography: {
      variants: [
        {
          props: { variant: 'h6' },
          style: {
            fontWeight: 400,
          },
        },
      ],
    },
    MuiChip: {
      variants: [
        {
          props: { size: 'extraSmall' },
          style: {
            height: '20px',
            fontSize: '0.75rem',
            '.MuiChip-label': {
              paddingLeft: '6px',
              paddingRight: '6px',
            },
          },
        },
      ],
    },
  },
};
