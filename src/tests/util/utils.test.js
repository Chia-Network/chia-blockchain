const utils = require("../../util/utils");

describe("utils", () => {
  describe("#unix_to_short_date", () => {
    it("converts unix timestamp to a short date", () => {
      const result = utils.unix_to_short_date(1589578957);

      expect(result).toBe("05/15/2020 22:42:37");
    });
  });
  describe("#get_query_variable", () => {
    beforeEach(() => {
      delete global.location;
      global.location = { search: "&x=y&foo=bar&baz=bop" };
    });
    it("gets query variable from location", () => {
      const result = utils.get_query_variable("foo");

      expect(result).toBe("bar");
    });

    it("cannot find a variable", () => {
      const result = utils.get_query_variable("chia");

      expect(result).toBeUndefined();
    });
  });
  describe("#hex_to_array", () => {
    it("converts lowercase hex string to an array", () => {
      const result = utils.hex_to_array("0xeeaa");

      expect(result).toEqual([238, 170]);
    });
    it("converts uppercase hex string to an array", () => {
      const result = utils.hex_to_array("0xEEAA");

      expect(result).toEqual([238, 170]);
    });
  });
  describe("#arr_to_hex", () => {
    it("converts an array to a hex string", () => {
      const result = utils.arr_to_hex([238, 170]);

      expect(result).toBe("eeaa");
    });
  });
});
