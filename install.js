#!/usr/bin/env node
/**
 * ruifeng-quote-internal install script
 *
 * Copies the skill to both Claude Code (~/.claude/skills/) and Hermes (~/.hermes/skills/).
 * Overwrites existing files to ensure sync from the single source of truth.
 *
 * 依赖: 主路径为自包含脚本(Python3 + requests)；CLI 工具 cli-anything-platform-service 可选,
 *   仅泰安联浏览器搜索/批量 Excel 等重流程需要独立安装:
 *   pip install -e /path/to/cli-anything-platform-service[data-clean]
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

const HOME = os.homedir();
const TARGETS = [
  path.join(HOME, '.claude', 'skills', 'ruifeng-quote-internal'),
  path.join(HOME, '.hermes', 'skills', 'ruifeng-quote-internal'),
];

const SOURCE = __dirname;

// Directories to sync
const DIRS = ['workflows', 'references', 'scripts', 'modules'];

function copyDir(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// Remove stale files that no longer exist in source
function cleanDir(dest, src) {
  if (!fs.existsSync(dest)) return;
  const entries = fs.readdirSync(dest, { withFileTypes: true });
  for (const entry of entries) {
    const destPath = path.join(dest, entry.name);
    const srcPath = path.join(src, entry.name);
    if (!fs.existsSync(srcPath)) {
      if (entry.isDirectory()) {
        fs.rmSync(destPath, { recursive: true });
      } else {
        fs.unlinkSync(destPath);
      }
    }
  }
}

for (const target of TARGETS) {
  console.log(`Installing to ${target}...`);

  // Ensure target directory exists
  fs.mkdirSync(target, { recursive: true });

  // Copy SKILL.md
  fs.copyFileSync(path.join(SOURCE, 'SKILL.md'), path.join(target, 'SKILL.md'));

  // Copy subdirectories
  for (const dir of DIRS) {
    const srcDir = path.join(SOURCE, dir);
    const destDir = path.join(target, dir);
    if (fs.existsSync(srcDir)) {
      copyDir(srcDir, destDir);
      cleanDir(destDir, srcDir);
    }
  }

  console.log(`  Done: ${target}`);
}

console.log('ruifeng-quote-internal installed successfully.');
console.log('');
console.log('提示: 日常查询/价格补全用自包含脚本即可(仅需 Python3 + requests)。');
console.log('泰安联浏览器搜索/批量 Excel 等重流程才需可选 CLI: pip install -e /path/to/cli-anything-platform-service[data-clean]');
