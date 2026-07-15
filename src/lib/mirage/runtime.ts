export type RuntimeEnv = Record<string, string | undefined>

function norm(value: string | undefined): string {
  return (value || '').trim().toLowerCase()
}

export function isProductionRuntime(env: RuntimeEnv = process.env): boolean {
  return norm(env.NODE_ENV) === 'production' || norm(env.VERCEL_ENV) === 'production' || norm(env.MIRAGE_ENV) === 'production'
}

export function isExplicitLocalDemoRuntime(env: RuntimeEnv = process.env): boolean {
  const value = norm(env.MIRAGE_LOCAL_DEMO)
  if (!value) return false
  return value === '1' || value === 'true' || value === 'yes' || value === 'on'
}

export function isLocalDevelopmentRuntime(env: RuntimeEnv = process.env): boolean {
  return !isProductionRuntime(env) && (norm(env.NODE_ENV) === 'development' || isExplicitLocalDemoRuntime(env))
}

export function missingSupabaseServerConfig(env: RuntimeEnv = process.env): boolean {
  const url = env.SUPABASE_URL || env.NEXT_PUBLIC_SUPABASE_URL
  const serviceRoleKey = env.SUPABASE_SERVICE_ROLE_KEY
  return !url || !serviceRoleKey
}
