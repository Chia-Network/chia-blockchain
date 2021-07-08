const hddcoin = require('../../util/hddcoin');

describe('hddcoin', () => {
  it('converts number mojo to hddcoin', () => {
    const result = hddcoin.mojo_to_hddcoin(1000000);

    expect(result).toBe(0.000001);
  });
  it('converts string mojo to hddcoin', () => {
    const result = hddcoin.mojo_to_hddcoin('1000000');

    expect(result).toBe(0.000001);
  });
  it('converts number mojo to hddcoin string', () => {
    const result = hddcoin.mojo_to_hddcoin_string(1000000);

    expect(result).toBe('0.000001');
  });
  it('converts string mojo to hddcoin string', () => {
    const result = hddcoin.mojo_to_hddcoin_string('1000000');

    expect(result).toBe('0.000001');
  });
  it('converts number hddcoin to mojo', () => {
    const result = hddcoin.hddcoin_to_mojo(0.000001);

    expect(result).toBe(1000000);
  });
  it('converts string hddcoin to mojo', () => {
    const result = hddcoin.hddcoin_to_mojo('0.000001');

    expect(result).toBe(1000000);
  });
  it('converts number mojo to colouredcoin', () => {
    const result = hddcoin.mojo_to_colouredcoin(1000000);

    expect(result).toBe(1000);
  });
  it('converts string mojo to colouredcoin', () => {
    const result = hddcoin.mojo_to_colouredcoin('1000000');

    expect(result).toBe(1000);
  });
  it('converts number mojo to colouredcoin string', () => {
    const result = hddcoin.mojo_to_colouredcoin_string(1000000);

    expect(result).toBe('1,000');
  });
  it('converts string mojo to colouredcoin string', () => {
    const result = hddcoin.mojo_to_colouredcoin_string('1000000');

    expect(result).toBe('1,000');
  });
  it('converts number colouredcoin to mojo', () => {
    const result = hddcoin.colouredcoin_to_mojo(1000);

    expect(result).toBe(1000000);
  });
  it('converts string colouredcoin to mojo', () => {
    const result = hddcoin.colouredcoin_to_mojo('1000');

    expect(result).toBe(1000000);
  });
});
