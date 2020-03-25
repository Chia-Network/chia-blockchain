var Big = require('big.js');
var units = require('./units');

// TODO: use bigint instead of float
const convert = (amount, from, to) => {
  if (Number.isNaN(parseFloat(amount)) || !Number.isFinite(amount)) {
    return 0;
  }

  const amountInFromUnit = Big(amount).times(units.getUnit(from));

  return parseFloat(amountInFromUnit.div(units.getUnit(to)));
};

class Chia {
  constructor(value, unit) {
    this._value = value;
    this._unit = unit;
  }

  to(newUnit) {
    this._value = convert(this._value, this._unit, newUnit);
    this._unit = newUnit;

    return this;
  }

  value() {
    return this._value;
  }

  format() {
    const displayUnit = units.getDisplay(this._unit);

    const { format, fractionDigits, trailing } = displayUnit;

    let options = { maximumFractionDigits: fractionDigits };

    if (trailing) {
      options = { minimumFractionDigits: fractionDigits };
    }

    let value;

    if (fractionDigits !== undefined) {
      const fractionPower = Big(10).pow(fractionDigits);
      value = parseFloat(Big(Math.floor(Big(this._value).times(fractionPower))).div(fractionPower));
    } else {
      value = this._value;
    }

    let formatted = format.replace('{amount}', parseFloat(value).toLocaleString(undefined, options));

    if (displayUnit.pluralize && this._value !== 1) {
      formatted += 's';
    }

    return formatted;
  }

  toString() {
    const displayUnit = units.getDisplay(this._unit);
    const { format, fractionDigits, trailing } = displayUnit;
    let options = { maximumFractionDigits: fractionDigits };
    return parseFloat(this._value).toLocaleString(undefined, options)
  }
}

const chia_formatter = (value, unit) => new Chia(value, unit);

chia_formatter.convert = convert;
chia_formatter.setDisplay = units.setDisplay;
chia_formatter.setUnit = units.setUnit;
chia_formatter.getUnit = units.getUnit;
chia_formatter.setFiat = (currency, rate, display = null) => {
  units.setUnit(currency, 1 / rate, display);
};

module.exports = chia_formatter