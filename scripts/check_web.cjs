// 前端门禁的单一入口：动态发现全部脚本和 UI 测试，不依赖 shell 通配符或手写名单。
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

// 目录缺失或零测试必须失败；发现不等于执行通过。
function discover(root) {
  const scripts = fs.readdirSync(path.join(root, 'src/myth/webui'), {withFileTypes: true})
    .filter(entry => entry.isFile() && entry.name.endsWith('.js'))
    .map(entry => 'src/myth/webui/' + entry.name).sort();
  const tests = fs.readdirSync(path.join(root, 'tests'), {withFileTypes: true})
    .filter(entry => entry.isFile() && /^test_.*_ui\.cjs$/.test(entry.name))
    .map(entry => 'tests/' + entry.name).sort();
  if (!scripts.length || !tests.length) throw new Error('Web gate requires production scripts and UI test files');
  return {scripts, tests};
}

// 每个子进程使用同一 Node；无 shell、有超时，保留失败状态与测试输出。
function check(root, run = spawnSync) {
  const catalog = discover(root);
  const commands = catalog.scripts.map(file => ['--check', file]);
  commands.push(['--test', ...catalog.tests]);
  for (const args of commands) {
    const result = run(process.execPath, args, {cwd: root, stdio: 'inherit', timeout: 120000});
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(`Web gate failed: ${args.join(' ')} (exit ${result.status}, signal ${result.signal || 'none'})`);
  }
  return catalog;
}

if (require.main === module) {
  const root = path.resolve(__dirname, '..');
  try {
    const args = process.argv.slice(2);
    if (args.length && !(args.length === 1 && args[0] === '--list')) throw new Error('Usage: node scripts/check_web.cjs [--list]');
    const catalog = args.length ? discover(root) : check(root);
    console.log(JSON.stringify({phase: args.length ? 'discovery_only' : 'executed', ...catalog}));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
module.exports = {discover, check};
