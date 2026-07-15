import { createBrowserClient } from '@supabase/ssr'

import { getSupabasePublishableKey, getSupabaseUrl } from './env'

let browserClient: ReturnType<typeof createBrowserClient> | null = null

export function createSupabaseBrowserClient() {
  if (browserClient) return browserClient

  const url = getSupabaseUrl()
  const key = getSupabasePublishableKey()

  if (!url || !key) {
    return null
  }

  browserClient = createBrowserClient(url, key)
  return browserClient
}

