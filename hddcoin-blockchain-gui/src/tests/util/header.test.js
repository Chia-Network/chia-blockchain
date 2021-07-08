const { createHash } = require('crypto');
const header = require('../../util/header');

describe('header', () => {
  beforeAll(() => {
    Object.assign(window, {
      crypto: {
        subtle: {
          digest: (algorithm, buf) => createHash('sha256').update(buf).digest(),
        },
      },
    });
  });
  describe('#hash_header', () => {
    it('hashes a header', async () => {
      const headerHash = await header.hash_header({
        data: {
          additions_root:
            '0x0000000000000000000000000000000000000000000000000000000000000000',
          aggregated_signature: null,
          coinbase: {
            amount: '14000000000000',
            parent_coin_info:
              '0x0000000000000000000000000000000000000000000000000000000000001268',
            puzzle_hash:
              '0xa927f72c69e0cc51098a41e1e0ea9d6894e961d1db80b4452cdf33e77f20da9e',
          },
          coinbase_signature: {
            sig: '0x4ba15d5506dce0bd8ade17dbb423a3277cc6de83b5667a9ac7511dd6e862eeb847a8918227ac0f774526dcd12d23494209d4c450c023369df0cb03e3d18a1dbd986723d2dd05e70cedb471c98a0b6bdf47ad99ef6168d179a8b68084eae4b892',
          },
          cost: '0',
          extension_data:
            '0x0000000000000000000000000000000000000000000000000000000000000000',
          fees_coin: {
            amount: '2000000000000',
            parent_coin_info:
              '0xd34ea9ed5d0f43bfd98dbdea2e3f14d637c965f9f9addb618d163504f7560714',
            puzzle_hash:
              '0xa927f72c69e0cc51098a41e1e0ea9d6894e961d1db80b4452cdf33e77f20da9e',
          },
          filter_hash:
            '0x0000000000000000000000000000000000000000000000000000000000000000',
          generator_hash:
            '0x0000000000000000000000000000000000000000000000000000000000000000',
          height: 4712,
          prev_header_hash:
            '0xb904cb37532f9b6f68088264c644d957f4aa844333d24bc9c2b30bf7859437d6',
          proof_of_space_hash:
            '0x1a853b8020f8c5b72ef4fb0656213cbfdb30bbc3dfe368527d6d83f50e7acf69',
          removals_root:
            '0x0000000000000000000000000000000000000000000000000000000000000000',
          timestamp: '1591371814',
          total_iters: '168608294357',
          weight: '3520789508784128',
        },
        plot_signature:
          '0x53d04fa0ee31bdc249e6db50161a6dc09d1c48ad011533b10a3eda25eb456a8b3562a1509b97f1931e334d5ed8ec6593133ecbbec5c423b733ea3cdfccc3022a7c09b0fc87fd4d0fd6cbfbedbb69d9fd43aab5c07e3452cb1f91524678340b50',
      });

      expect(headerHash).toBe(
        '365d165727ba1279aceecf8a4a8188a7a5152e06bf7825584f272014947af7e5',
      );
    });
  });
});
