const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const host = '127.0.0.1';
const types = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.png': 'image/png' };

function createFixtureServer() {
  return http.createServer(async (request, response) => {
    let pathname;
    try {
      pathname = decodeURIComponent(new URL(request.url, `http://${host}`).pathname);
    } catch (error) {
      response.writeHead(400).end('Invalid URL');
      return;
    }
    const target = path.resolve(root, '.' + pathname);
    if (target !== root && !target.startsWith(root + path.sep)) {
      response.writeHead(403).end('Forbidden');
      return;
    }
    const file = target === root ? path.join(root, 'index.html') : target;
    try {
      const content = await fs.readFile(file);
      response.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
      response.end(content);
    } catch (error) {
      response.writeHead(error.code === 'ENOENT' || error.code === 'EISDIR' ? 404 : 500).end();
    }
  });
}

if (require.main === module) {
  const port = Number(process.env.LAYOUT_FIXTURE_PORT || 4178);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid fixture port');
  createFixtureServer().listen(port, host, () => process.stdout.write(`Layout fixture server: http://${host}:${port}\n`));
}

module.exports = { createFixtureServer };
