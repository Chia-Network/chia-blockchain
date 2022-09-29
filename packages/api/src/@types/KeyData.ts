type KeyData = {
  fingerprint: number;
  label: string | null;
  publicKey: string;
  secrets: {
    mnemonic: string[];
    entropy: string;
    privateKey: string;
  } | null;
};

export default KeyData;
