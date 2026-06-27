import type { PortfolioAccountItem } from '../types/portfolio';

export const CA_ACCOUNT_TYPES = [
  'rrsp',
  'tfsa',
  'fhsa',
  'rrif',
  'resp',
  'lira',
  'rdsp',
  'non_registered_cash',
  'non_registered_margin',
] as const;

const ACCOUNT_TYPES_BY_MARKET: Record<string, readonly string[]> = {
  ca: CA_ACCOUNT_TYPES,
};

export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  rrsp: 'RRSP',
  tfsa: 'TFSA',
  fhsa: 'FHSA',
  rrif: 'RRIF',
  resp: 'RESP',
  lira: 'LIRA',
  rdsp: 'RDSP',
  non_registered_cash: '非注册现金',
  non_registered_margin: '非注册保证金',
};

export function accountTypesForMarket(market: string): string[] {
  return [...(ACCOUNT_TYPES_BY_MARKET[(market || '').trim().toLowerCase()] ?? [])];
}

export interface AccountTypeGroup<T> {
  key: string;
  label: string;
  accounts: T[];
}

export function groupAccountsByType<T extends Pick<PortfolioAccountItem, 'accountType'>>(
  accounts: T[],
): AccountTypeGroup<T>[] {
  const buckets = new Map<string, T[]>();
  for (const account of accounts) {
    const key = (account.accountType || '').trim().toLowerCase();
    const bucket = buckets.get(key) ?? [];
    bucket.push(account);
    buckets.set(key, bucket);
  }

  const known = CA_ACCOUNT_TYPES.filter((key) => buckets.has(key));
  const custom = [...buckets.keys()].filter(
    (key) => key !== '' && !CA_ACCOUNT_TYPES.includes(key as typeof CA_ACCOUNT_TYPES[number]),
  );
  const orderedKeys = [...known, ...custom, ...(buckets.has('') ? [''] : [])];

  return orderedKeys.map((key) => ({
    key,
    label: key ? (ACCOUNT_TYPE_LABELS[key] ?? key) : '未分类',
    accounts: buckets.get(key) ?? [],
  }));
}
