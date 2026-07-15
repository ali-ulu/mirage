import { describe, expect, it } from 'vitest'

import { isNextTrackRouteEnabled, classifyOpenerApp } from '@/app/api/track/[token]/route'
import { isProductionRuntime, isLocalDevelopmentRuntime, missingSupabaseServerConfig } from '@/lib/mirage/runtime'

describe('MIRAGE production boundary helpers', () => {
  it('production runtime is detected from NODE_ENV, VERCEL_ENV, or MIRAGE_ENV', () => {
    expect(isProductionRuntime({ NODE_ENV: 'production' })).toBe(true)
    expect(isProductionRuntime({ VERCEL_ENV: 'production' })).toBe(true)
    expect(isProductionRuntime({ MIRAGE_ENV: 'production' })).toBe(true)
    expect(isProductionRuntime({ NODE_ENV: 'development' })).toBe(false)
  })

  it('Next.js track route is local-demo only and disabled in production', () => {
    expect(isNextTrackRouteEnabled({ NODE_ENV: 'production', MIRAGE_LOCAL_DEMO: 'true' })).toBe(false)
    expect(isNextTrackRouteEnabled({ NODE_ENV: 'development' })).toBe(true)
    expect(isNextTrackRouteEnabled({ MIRAGE_LOCAL_DEMO: 'true' })).toBe(true)
  })

  it('local demo runtime never overlaps production runtime', () => {
    expect(isLocalDevelopmentRuntime({ NODE_ENV: 'development' })).toBe(true)
    expect(isLocalDevelopmentRuntime({ NODE_ENV: 'production', MIRAGE_LOCAL_DEMO: 'true' })).toBe(false)
  })

  it('production dashboard server config requires Supabase URL and service role key', () => {
    expect(missingSupabaseServerConfig({ SUPABASE_URL: 'https://example.supabase.co' })).toBe(true)
    expect(missingSupabaseServerConfig({ SUPABASE_SERVICE_ROLE_KEY: 'service-role' })).toBe(true)
    expect(
      missingSupabaseServerConfig({
        SUPABASE_URL: 'https://example.supabase.co',
        SUPABASE_SERVICE_ROLE_KEY: 'service-role',
      }),
    ).toBe(false)
  })

  it('classifies common opener apps without executing client-side code', () => {
    expect(classifyOpenerApp('LibreOffice/7.6')).toBe('libreoffice')
    expect(classifyOpenerApp('Microsoft Office Excel')).toBe('excel')
    expect(classifyOpenerApp('Mozilla/5.0')).toBe('browser')
    expect(classifyOpenerApp('Unknown')).toBe('unknown')
  })
})
