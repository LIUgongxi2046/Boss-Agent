const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {expect} = require('@playwright/test');

const root = path.resolve(__dirname, '../..');
function provision(directory) {
  assert.equal(path.dirname(path.resolve(directory)), path.join(root, 'validation/.work'));
  execFileSync(path.join(root, 'validation/.venv/bin/python'), [path.join(root, 'scripts/provision_boss_accounts.py'),
    '--directory', path.join(directory, 'accounts')], {cwd: root, env: {...process.env,
      TMPDIR: path.join(root, 'validation/.work/tmp')}, timeout: 30000});
  const accounts = JSON.parse(fs.readFileSync(path.join(directory, 'accounts/credentials.json')));
  return Object.fromEntries(accounts.map(account => [account.role, account]));
}
function headers(accounts, role) {
  const account = accounts[role]; assert.ok(account);
  return {'X-Boss-Username': account.username, 'X-Boss-Password': account.password, 'X-Boss-Role': role};
}
async function bootstrap(origin, accounts, role) {
  const response = await fetch(origin + '/webui/bootstrap', {headers: headers(accounts, role)});
  assert.equal(response.status, 200); return response.json();
}
async function login(page, accounts, role) {
  await expect(page.getByLabel('账号', {exact: true})).toBeEnabled();
  if (role === 'MAINTAINER') await page.getByRole('button', {name: '技术维护', exact: true}).click();
  await page.getByLabel('账号', {exact: true}).fill(accounts[role].username);
  await page.getByLabel('密码', {exact: true}).fill(accounts[role].password);
  await page.getByRole('button', {name: /^(登录|重新认证)$/}).click();
  await page.locator('.boss-v6[data-role="' + role + '"]').waitFor();
}
async function logout(page) {
  await page.getByTitle('退出当前身份', {exact: true}).click();
  await expect(page.getByLabel('账号', {exact: true})).toBeEnabled();
}
module.exports = {provision, headers, bootstrap, login, logout};
