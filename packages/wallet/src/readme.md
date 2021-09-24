# Information for developers

## How to use local test and farm locally

If you want to use local farming and not to connect to the network you need to set
variable LOCAL_TEST in your .env file. This file is located in the root directory of your chia-blockchain-gui directory.

```env
LOCAL_TEST=true
```

## Best practices

- using TypeScript and CSS-in-JS because material-ui is using CSS-in-JS
- Only one exported component per file
- Same file name like exported function / component / class
- CSS, gprahql file next to the component file with different extension
- turn on eslint in your IDE
- create unit tests for all components
- all styled components use prefix Styled. For example const StyledMyComponent = styled....
