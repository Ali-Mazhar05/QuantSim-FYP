import type { MarketComponents } from '../../../services/generated'

// Typed against the generated schema, so a renamed or removed field fails the type check here
// too. When contracts/fixtures (C3) lands, handlers load those recorded files instead.
export const environments: MarketComponents['schemas']['EnvironmentOut'][] = [
  {
    id: '6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c01',
    name: 'Big tech 2020 replay',
    type: 'historical_replay',
    universe: 'Big tech',
    instrument_ids: [
      '0b6d7f3a-1111-4a00-8000-000000000001',
      '0b6d7f3a-1111-4a00-8000-000000000002',
    ],
    symbols: ['AAPL', 'MSFT'],
    start_date: '2020-01-02',
    end_date: '2020-12-31',
    frequency: 'daily',
    status: 'ready',
    created_by: '9d1e5c7b-2222-4b00-8000-000000000001',
    created_at: '2026-11-10T09:00:00Z',
  },
  {
    id: '6f1c2a4e-3b8d-4f7a-9c21-0a5e7d9b1c02',
    name: 'Synthetic draft',
    type: 'synthetic',
    universe: 'Big tech',
    instrument_ids: ['0b6d7f3a-1111-4a00-8000-000000000001'],
    symbols: ['AAPL'],
    start_date: '2025-01-02',
    end_date: '2025-12-31',
    frequency: 'daily',
    status: 'draft',
    created_by: '9d1e5c7b-2222-4b00-8000-000000000001',
    created_at: '2026-11-12T09:00:00Z',
  },
]
