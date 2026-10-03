import type { NextConfig } from "next";

/**
 * #52 — "next dev" uzerinde hydration/flaky sorununun KOK NEDENI.
 *
 * Turbopack, proje dizininin USTUNDE baska bir package-lock.json bulunca
 * (bu makinede: C:\Users\<kullanici>\package-lock.json) workspace root'u
 * proje degil, ust dizin (kullanici profili) saniyor:
 *
 *   ⚠ Next.js inferred your workspace root, but it may not be correct.
 *     We detected multiple lockfiles and selected the directory of
 *     C:\Users\<kullanici>\package-lock.json as the root directory.
 *
 * Yanlis kok secildiginde Turbopack tum kullanici profilini izlemeye/derlemeye
 * calisiyor; dev derlemesi yavasliyor ve zaman zaman modul cozumleme
 * tamamlanmadigi icin sayfa render edilip HIDRATE OLMUYOR (paneller
 * "YUKLENIYOR..." kalir, /api istegi hic gitmez). Production etkilenmez.
 *
 * Cozum: workspace root'u acikca proje dizinine sabitle. Boylece proje,
 * ustunde baska bir lockfile olan herhangi bir makinede de dogru derlenir.
 *
 *   Ref: https://nextjs.org/docs/app/api-reference/config/next-config-js/turbopack
 *        https://github.com/vercel/next.js/issues/92978
 *
 * NOT: process.cwd() yerine __dirname kullan (cwd, komutun calistirildigi
 * yere bagli; __dirname her zaman bu config dosyasinin dizinidir).
 */
const projectRoot = __dirname;

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Turbopack (next dev) icin dogru workspace root.
  turbopack: {
    root: projectRoot,
  },
  // "output: standalone" build'inde dosya izleme koku de acikca verilir;
  // aksi halde yanlis kok yuzunden kullanici profili taranabilir.
  outputFileTracingRoot: projectRoot,
};

export default nextConfig;

