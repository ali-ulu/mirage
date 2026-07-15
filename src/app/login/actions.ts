'use server'

import { redirect } from 'next/navigation'

import { createSupabaseServerClient } from '@/lib/supabase/server'

function getRedirectTarget(nextPath: string | null): string {
  if (!nextPath) return '/auth/check-email'
  if (!nextPath.startsWith('/')) return '/auth/check-email'
  return `/auth/check-email?next=${encodeURIComponent(nextPath)}`
}

export async function sendMagicLink(formData: FormData) {
  const email = String(formData.get('email') || '').trim()
  const nextPath = String(formData.get('next') || '').trim()

  if (!email) {
    redirect('/login?error=missing-email')
  }

  const supabase = await createSupabaseServerClient()
  if (!supabase) {
    redirect('/login?error=supabase-not-configured')
  }

  const baseUrl =
    process.env.NEXT_PUBLIC_SITE_URL ||
    (process.env.NEXT_PUBLIC_VERCEL_URL
      ? `https://${process.env.NEXT_PUBLIC_VERCEL_URL}`
      : 'http://localhost:3000')

  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: {
      emailRedirectTo: `${baseUrl}/auth/confirm?next=${encodeURIComponent(nextPath || '/')}`,
      shouldCreateUser: true,
    },
  })

  if (error) {
    redirect(`/login?error=${encodeURIComponent(error.message)}`)
  }

  redirect(getRedirectTarget(nextPath || '/'))
}
