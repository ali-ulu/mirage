/* eslint-disable @typescript-eslint/no-require-imports */
const fs = require('fs');
const path = require('path');

function copyDirSync(src, dest) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDirSync(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// Copy .next/static to .next/standalone/.next/static
copyDirSync(
  path.join(__dirname, '..', '.next', 'static'),
  path.join(__dirname, '..', '.next', 'standalone', '.next', 'static')
);

// Copy public to .next/standalone/public
copyDirSync(
  path.join(__dirname, '..', 'public'),
  path.join(__dirname, '..', '.next', 'standalone', 'public')
);

console.log('Static assets copied successfully to standalone folder.');
