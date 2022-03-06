const utils = require('../../util/utils');

describe('utils', () => {
  describe('#hex_to_array', () => {
    it('converts lowercase hex string to an array', () => {
      const result = utils.hex_to_array('0xeeaa');

      expect(result).toEqual([238, 170]);
    });
    it('converts uppercase hex string to an array', () => {
      const result = utils.hex_to_array('0xEEAA');

      expect(result).toEqual([238, 170]);
    });
  });
  describe('#arr_to_hex', () => {
    it('converts an array to a hex string', () => {
      const result = utils.arr_to_hex([238, 170]);

      expect(result).toBe('eeaa');
    });
  });
});
