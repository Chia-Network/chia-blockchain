import { randomBytes } from 'crypto';

export default function useNFTMetadata({
  id,
} : {
  walletId: number;
  id: string;
}) {
  return {
    id,
    metadata: {
      owner: '@DrSpaceman',
      name: 'Mocked NFT title ' + randomBytes(1).toString('hex'),
      description: 'Mocked NFT description Lorem Ipsum is simply dummy text of the printing and typesetting industry. Lorem Ipsum has been the industry\'s standard dummy text ever since the 1500s, when an unknown printer took a galley of type and scrambled it to make a type specimen book. It has survived not only five centuries, but also the leap into electronic typesetting, remaining essentially unchanged. It was popularised in the 1960s with the release of Letraset sheets containing Lorem Ipsum passages, and more recently with desktop publishing software like Aldus PageMaker including versions of Lorem Ipsum.',
      image: `https://picsum.photos/800/800?random=${id}`,
      price: Math.floor(Math.random() * 100) * 10**12,
      total: Math.floor(Math.random() * 10000),
      marketplace: 'NFT Marketplace',
      hash: randomBytes(32).toString('hex'),
      contractAddress: `xch${randomBytes(20).toString('hex')}`,
      urls: ['https://www.nftmarketplace.com/'],
      standard: 'NFT1',
      activity: [{
        date: new Date() - Math.floor(Math.random() * 100) * 24 * 60 * 60 * 1000,
        type: 'transfer',
        from: '@Anderson',
        to: '@DrSpaceman',
        amount: Math.floor(Math.random() * 100) * 10**12,
      }, {
        date: new Date() - Math.floor(Math.random() * 100) * 24 * 60 * 60 * 1000,
        type: 'transfer',
        from: '@Smith',
        to: '@Anderson',
        amount: Math.floor(Math.random() * 100) * 10**12,
      }, {
        date: new Date() - Math.floor(Math.random() * 100) * 24 * 60 * 60 * 1000,
        type: 'transfer',
        from: '@PeterParker',
        to: '@Smith',
        amount: Math.floor(Math.random() * 100) * 10**12,
      }],
    },
    isLoading: false,
  };
}
