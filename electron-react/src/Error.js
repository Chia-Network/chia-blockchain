import React from 'react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI.
    return { hasError: true };
  }

  componentDidCatch(error) {
    // Catch errors in any components below and re-render with error message
    this.setState({
      hasError: error,
    });
    // You can also log error messages to an error reporting service here
  }

  render() {
    if (this.state.hasError) {
      // You can render any custom fallback UI
      return (
        <React.Fragment>
          <h1
            className="animated infinite bounce"
            style={{
              textAlign: 'center',
              margin: 'auto',
              position: 'absolute',
              height: '100px',
              width: '100px',
              top: '0px',
              bottom: '0px',
              left: '0px',
              right: '0px',
            }}
          >
            Something went wrong
          </h1>
        </React.Fragment>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
