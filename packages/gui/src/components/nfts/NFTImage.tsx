import { useEffect, useState } from 'react';
import getRemoteFileContent from '../../uril/getRemoteFileContent';

enum NFTImageState {
  LOADING,
  VERIFIED,
  ERROR,
};

export type NFTImageProps = {
  url: string;
  hash: string;
};

export default function NFTImage(props: NFTImageProps) {
  const [state, setState] = useState<NFTImageState>(NFTImageState.LOADING);

  async function handleVerifyHash(url: string, hash: string) {
    try {
      setState(NFTImageState.LOADING);
    }
  }

  useEffect(() => {
    handleVerifyHash(url, hash);
  }, [url, hash]);

  return (
    <div>
      {state === NFTImageState.LOADING && <div>Loading...</div>}
    </div>
  );
}

0c5083a0774434fae4169d234c7ae646632335c0807d29fc351761519108a95a
