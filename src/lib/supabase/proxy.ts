import { createServerClient } from '@supabase/ssr'
import { NextResponse, type NextRequest } from 'next/server'

import { getSupabasePublishableKey, getSupabaseUrl } from './env'

const PUBLIC_PATHS = ['/login', '/auth']

export async function updateSession(request: NextRequest) {
  const url = getSupabaseUrl()
  const key = getSupabasePublishableKey()
  const pathname = request.nextUrl.pathname

  let supabaseResponse = NextResponse.next({ request })

  if (!url || !key) {
    return supabaseResponse
  }

  const supabase = createServerClient(url, key, {
    cookies: {
      getAll() {
        return request.cookies.getAll()
      },
      setAll(cookiesToSet, headers) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value))
        supabaseResponse = NextResponse.next({ request })
        cookiesToSet.forEach(({ name, value, options }) =>
          supabaseResponse.cookies.set(name, value, options)
        )
        Object.entries(headers).forEach(([headerName, value]) =>
          supabaseResponse.headers.set(headerName, value)
        )
      },
    },
  })

  const { data } = await supabase.auth.getClaims()
  const hasUser = Boolean(data?.claims)
  const isPublicRoute = PUBLIC_PATHS.some((prefix) => pathname.startsWith(prefix))

  if (!hasUser && !isPublicRoute) {
    const redirectUrl = request.nextUrl.clone()
    redirectUrl.pathname = '/login'
    redirectUrl.searchParams.set('next', pathname)
    return NextResponse.redirect(redirectUrl)
  }

  return supabaseResponse
}

