import { beforeEach, describe, expect, it, vi } from 'vitest';
import { portfolioApi } from '../portfolio';

const { post } = vi.hoisted(() => ({
  post: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    post,
  },
}));

describe('portfolioApi account types', () => {
  beforeEach(() => {
    post.mockReset();
  });

  it('sends accountType as account_type and maps it back to camelCase', async () => {
    post.mockResolvedValueOnce({
      data: {
        id: 9,
        name: 'RRSP',
        market: 'ca',
        base_currency: 'CAD',
        account_type: 'rrsp',
        is_active: true,
      },
    });

    const result = await portfolioApi.createAccount({
      name: 'RRSP',
      market: 'ca',
      baseCurrency: 'CAD',
      accountType: 'rrsp',
    });

    expect(post).toHaveBeenCalledWith('/api/v1/portfolio/accounts', {
      name: 'RRSP',
      broker: undefined,
      market: 'ca',
      base_currency: 'CAD',
      owner_id: undefined,
      account_type: 'rrsp',
    });
    expect(result.accountType).toBe('rrsp');
  });
});
