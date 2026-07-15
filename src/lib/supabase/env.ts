// NOTE: these are read lazily on every call rather than captured once at
// module-load time. Reading them at module scope froze the values at import
// (empty in any context where env vars are populated after the module loads —
// e.g. tests that set process.env at runtime, or deferred/edge runtimes),
// which silently disabled the Supabase client even when config was present.

export function getSupabaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_SUPABASE_URL ||
    process.env.SUPABASE_URL ||
    ''
  );
}

export function getSupabasePublishableKey(): string {
  return (
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
    ''
  );
}

export function getSupabaseServiceRoleKey(): string {
  return process.env.SUPABASE_SERVICE_ROLE_KEY || '';
}

