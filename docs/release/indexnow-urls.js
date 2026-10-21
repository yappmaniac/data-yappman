// node docs/release/indexnow-urls.js FILE... : turns changed file paths into the public page URLs to ping (HTML pages only).
// Skips held pages (_held/), docs, the 404 page and the Google verification file. Prints one URL per line.
const HOST = "https://data.yappman.com";
function urlFor(f) {
  f = f.split(String.fromCharCode(92)).join("/");
  if (!/\.html$/.test(f)) return null;
  if (/^(_held|docs|assets|\.github)\//.test(f) || f === "404.html" || /^google[0-9a-f]+\.html$/.test(f)) return null;
  if (f === "index.html") return HOST + "/";
  const m = /^(.*)\/index\.html$/.exec(f);
  return m ? HOST + "/" + m[1] + "/" : null;
}
if (require.main === module) {
  const urls = [...new Set(process.argv.slice(2).map(urlFor).filter(Boolean))].sort();
  console.log(urls.join("\n"));
}
module.exports = { urlFor };
