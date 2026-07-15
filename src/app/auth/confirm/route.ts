import { type EmailOtpType } from '@supabase/supabase-js'
import { NextResponse, type NextRequest } from 'next/server'

import { createSupabaseServerClient } from '@/lib/supabase/server'

export async function GET(request: NextRequest) {
  const supabase = await createSupabaseServerClient()
  if (!supabase) {
    return NextResponse.redirect(new URL('/login?error=supabase-not-configured', request.url))
  }

  const token_hash = request.nextUrl.searchParams.get('token_hash')
  const type = request.nextUrl.searchParams.get('type') as EmailOtpType | null
  const nextPath = request.nextUrl.searchParams.get('next') || '/'
  const safeNextPath = nextPath.startsWith('/') ? nextPath : '/'

  if (!token_hash || !type) {
    return NextResponse.redirect(new URL('/auth/error', request.url))
  }

  const { error } = await supabase.auth.verifyOtp({ token_hash, type })
  if (error) {
    return NextResponse.redirect(new URL('/auth/error', request.url))
  }

  return NextResponse.redirect(new URL(safeNextPath, request.url))
}
