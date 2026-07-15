import Link from 'next/link'

import { sendMagicLink } from './actions'

export default function LoginPage({
  searchParams,
}: {
  searchParams?: { next?: string; error?: string }
}) {
  const nextPath = searchParams?.next || '/'
  const error = searchParams?.error

  return (
    <main className="min-h-screen bg-white text-black font-mono flex items-center justify-center px-6 py-12">
      <div className="max-w-lg w-full border-2 border-black shadow-[10px_10px_0_0_#000] bg-white p-6">
        <div className="mb-6">
          <div className="text-xs uppercase tracking-[0.3em] text-black/60">MIRAGE</div>
          <h1 className="text-4xl font-black tracking-tight mt-2">Sign in</h1>
          <p className="mt-2 text-sm text-black/70">
            We’ll send a magic link to your email, then take you back to the dashboard.
          </p>
        </div>

        {error ? (
          <div className="mb-4 border-2 border-black bg-red-200 px-3 py-2 text-sm">
            Login error: {error}
          </div>
        ) : null}

        <form action={sendMagicLink} className="space-y-4">
          <input type="hidden" name="next" value={nextPath} />
          <label className="block">
            <span className="text-xs uppercase tracking-widest font-bold">Email</span>
            <input
              name="email"
              type="email"
              required
              placeholder="you@company.com"
              className="mt-2 w-full border-2 border-black px-3 py-2 outline-none"
            />
          </label>

          <button
            type="submit"
            className="w-full border-2 border-black bg-black text-white px-4 py-3 font-bold uppercase tracking-widest hover:bg-white hover:text-black transition-colors"
          >
            Send magic link
          </button>
        </form>

        <div className="mt-6 text-xs text-black/60">
          Need help? <Link href="/" className="underline">Back to dashboard</Link>
        </div>
      </div>
    </main>
  )
}

