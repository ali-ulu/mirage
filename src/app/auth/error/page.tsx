import Link from 'next/link'

export default function AuthErrorPage() {
  return (
    <main className="min-h-screen bg-white text-black font-mono flex items-center justify-center px-6 py-12">
      <div className="max-w-md w-full border-2 border-black shadow-[10px_10px_0_0_#000] bg-red-100 p-6">
        <div className="text-xs uppercase tracking-[0.3em] text-black/60">MIRAGE</div>
        <h1 className="text-3xl font-black tracking-tight mt-2">Login error</h1>
        <p className="mt-3 text-sm">Your authentication link could not be verified.</p>
        <Link
          href="/login"
          className="inline-block mt-6 border-2 border-black bg-black text-white px-4 py-2 font-bold uppercase tracking-widest"
        >
          Try again
        </Link>
      </div>
    </main>
  )
}

