import { describe, expect, it } from 'vitest';
import {
  CA_ACCOUNT_TYPES,
  accountTypesForMarket,
  groupAccountsByType,
} from '../accountTypes';

describe('accountTypes', () => {
  it('returns Canadian options only for the Canadian market', () => {
    expect(accountTypesForMarket('ca')).toEqual([...CA_ACCOUNT_TYPES]);
    expect(accountTypesForMarket(' CA ')).toEqual([...CA_ACCOUNT_TYPES]);
    expect(accountTypesForMarket('us')).toEqual([]);
  });

  it('groups known then custom account types with untyped accounts last', () => {
    const groups = groupAccountsByType([
      { id: 1, accountType: 'rrsp' },
      { id: 2 },
      { id: 3, accountType: 'custom_family' },
      { id: 4, accountType: 'rrsp' },
    ]);

    expect(groups.map((group) => group.key)).toEqual(['rrsp', 'custom_family', '']);
    expect(groups[0].accounts.map((account) => account.id)).toEqual([1, 4]);
    expect(groups[2].accounts.map((account) => account.id)).toEqual([2]);
  });
});
