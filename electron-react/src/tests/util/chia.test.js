const chia = require("../../util/chia");

describe("chia", () => {
  it("converts number mojo to chia", () => {
    const result = chia.mojo_to_chia(1000000);

    expect(result).toBe(0.000001);
  });
  it("converts string mojo to chia", () => {
    const result = chia.mojo_to_chia("1000000");

    expect(result).toBe(0.000001);
  });
  it("converts number mojo to chia string", () => {
    const result = chia.mojo_to_chia_string(1000000);

    expect(result).toBe("0.000001");
  });
  it("converts string mojo to chia string", () => {
    const result = chia.mojo_to_chia_string("1000000");

    expect(result).toBe("0.000001");
  });
  it("converts number chia to mojo", () => {
    const result = chia.chia_to_mojo(0.000001);

    expect(result).toBe(1000000);
  });
  it("converts string chia to mojo", () => {
    const result = chia.chia_to_mojo("0.000001");

    expect(result).toBe(1000000);
  });
  it("converts number mojo to colouredcoin", () => {
    const result = chia.mojo_to_colouredcoin(1000000);

    expect(result).toBe(1000);
  });
  it("converts string mojo to colouredcoin", () => {
    const result = chia.mojo_to_colouredcoin("1000000");

    expect(result).toBe(1000);
  });
  it("converts number mojo to colouredcoin string", () => {
    const result = chia.mojo_to_colouredcoin_string(1000000);

    expect(result).toBe("1,000");
  });
  it("converts string mojo to colouredcoin string", () => {
    const result = chia.mojo_to_colouredcoin_string("1000000");

    expect(result).toBe("1,000");
  });
  it("converts number colouredcoin to mojo", () => {
    const result = chia.colouredcoin_to_mojo(1000);

    expect(result).toBe(1000000);
  });
  it("converts string colouredcoin to mojo", () => {
    const result = chia.colouredcoin_to_mojo("1000");

    expect(result).toBe(1000000);
  });
});
