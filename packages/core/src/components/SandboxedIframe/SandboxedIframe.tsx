import React, { useEffect, useState, memo } from 'react';
import styled from 'styled-components';

const StyledIframe = styled(({ isVisible, ...rest }) => <iframe {...rest} />)`
  position: relative;
  width: 100%;
  height: 100%;
  opacity: ${({ isVisible }) => (isVisible ? 1 : 0)};
`;

export type SandboxIframeProps = {
  srcDoc: string;
  height?: number | string;
  width?: number | string;
  onLoadedChange?: (loaded: boolean) => void;
  hideUntilLoaded?: boolean;
  allowPointerEvents?: boolean;
};

function SandboxedIframe(props: SandboxIframeProps) {
  const {
    srcDoc,
    height = '300px',
    width,
    onLoadedChange,
    hideUntilLoaded = false,
    allowPointerEvents = false,
  } = props;

  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    onLoadedChange?.(false);
  }, [srcDoc]);

  function handleLoad() {
    setLoaded(true);
    onLoadedChange?.(true);
  }

  const isVisible = hideUntilLoaded ? loaded : true;

  return (
    <StyledIframe
      srcDoc={srcDoc}
      sandbox=""
      height={height}
      width={width}
      frameBorder="0"
      onLoad={handleLoad}
      isVisible={isVisible}
      allowFullScreen={true}
      style={{ pointerEvents: allowPointerEvents ? 'auto' : 'none' }}
    />
  );
}

export default memo(SandboxedIframe);
