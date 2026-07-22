#!/usr/bin/env node
/**
 * ruifeng-quote-internal install script (symlink mode)
 *
 * Creates symlinks from each agent's skills directory to this repo,
 * so edits here take effect everywhere immediately — no re-install needed.
 * Idempotent: correct links are kept; real dirs are backed up as <name>.bak.
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = os.homedir();
const SOURCE = __dirname;
const TARGETS = [path.join(HOME,'.claude','skills','ruifeng-quote-internal'), path.join(HOME,'.hermes','skills','ruifeng-quote-internal')];

for (const link of TARGETS) {
  fs.mkdirSync(path.dirname(link), { recursive: true });
  if (fs.existsSync(link)) {
    const stat = fs.lstatSync(link);
    if (stat.isSymbolicLink()) {
      if (fs.realpathSync(link) === fs.realpathSync(SOURCE)) {
        console.log(`  ok (already linked): ${link}`);
        continue;
      }
      fs.unlinkSync(link);
    } else {
      const bak = link + '.bak';
      fs.rmSync(bak, { recursive: true, force: true });
      fs.renameSync(link, bak);
      console.log(`  backed up real dir -> ${bak}`);
    }
  }
  fs.symlinkSync(SOURCE, link, 'dir');
  console.log(`  linked: ${link} -> ${SOURCE}`);
}
console.log('ruifeng-quote-internal installed (symlink mode).');
