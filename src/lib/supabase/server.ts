import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

import { getSupabasePublishableKey, getSupabaseUrl } from './env'

export async function createSupabaseServerClient() {
  const url = getSupabaseUrl()
  const key = getSupabasePublishableKey()
  const cookieStore = await cookies()

  if (!url || !key) {
    return null
  }

  return createServerClient(url, key, {
    cookies: {
      getAll() {
        return cookieStore.getAll()
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          )
        } catch {
          // Server Components can't always mutate cookies; middleware refreshes sessions.
        }
      },
    },
  })
}

