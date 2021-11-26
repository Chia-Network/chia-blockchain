// deprecated
import Unit from '../constants/Unit';
import UnitValue from '../constants/UnitValue';
import UnitAliases from '../constants/UnitAliases';

type Display = {
  format: string;
  fractionDigits: number;
};


const display: {
  [key in Unit]: Display;
} = {
  chia: {
    format: '{amount} XCH',
    fractionDigits: 12,
  },
  mojo: {
    format: '{amount} MJ',
    fractionDigits: 0,
  },
  cat: {
    format: '{amount} CAT',
    fractionDigits: 3,
  },
};

function getUnitNameByAlias(unitName: string): Unit {
  const name = unitName.toLowerCase();

  const alias = Object.keys(UnitAliases).find((key) => !!UnitAliases[key]?.includes(name));
  if (alias === undefined) {
    throw new Error(`Unit '${unitName}' is not supported`);
  }

  return alias as Unit;
}

function getUnitName(unitName: string): Unit {
  const name = unitName.toLowerCase();

  if (name in Unit) {
    return name as Unit;
  }

  return getUnitNameByAlias(unitName);
}

export default function getUnitValue(unitName: string): number {
  return UnitValue[getUnitName(unitName)];
}

/*
export function getDisplay(unitName: string): Display {
  const unit = getUnitName(unitName);
  return display[unit];
}
*/