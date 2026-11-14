import { cp, mkdir, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = path.join(root, 'backend', 'web');
const output = path.join(root, 'native-dist');
const rawApiBase = (process.env.KISANX_API_BASE || '').trim();

if (!rawApiBase) {
  throw new Error('Set KISANX_API_BASE to the HTTPS origin of your hosted FastAPI service before building.');
}

let apiUrl;
try {
  apiUrl = new URL(rawApiBase);
} catch {
  throw new Error('KISANX_API_BASE must be a valid URL, such as https://api.example.com.');
}

const localHost = ['localhost', '127.0.0.1', '10.0.2.2'].includes(apiUrl.hostname);
if (apiUrl.protocol !== 'https:' && !(localHost && apiUrl.protocol === 'http:')) {
  throw new Error('Use HTTPS for the hosted API. HTTP is allowed only for local development hosts.');
}
if (apiUrl.pathname !== '/' || apiUrl.search || apiUrl.hash || apiUrl.username || apiUrl.password) {
  throw new Error('KISANX_API_BASE must be only the API origin, without a path, query, credentials, or fragment.');
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(source, output, { recursive: true });
const config = `window.KISANX_API_BASE = ${JSON.stringify(apiUrl.origin)};\nwindow.KISANX_IS_NATIVE = true;\n`;
await writeFile(path.join(output, 'assets', 'app-config.js'), config, 'utf8');
console.log(`Prepared native web assets in ${path.relative(root, output)} for ${apiUrl.origin}`);
