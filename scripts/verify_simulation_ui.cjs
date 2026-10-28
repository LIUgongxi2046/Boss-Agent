const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

const root = path.resolve(__dirname, '..');
const {chromium} = require(path.join(root, 'validation/desktop/node_modules/playwright'));
const directory = path.join(root, 'validation/.work/comprehensive-simulation-20261028');
const output = path.join(root, '.work/simulation-20261028/ui-agents.json');
const account = JSON.parse(fs.readFileSync(path.join(directory, 'accounts/credentials.json'))).find(row => row.role === 'BOSS');
const origin = 'http://127.0.0.1:9082';
const requested = process.argv.slice(2);
const records = fs.existsSync(output) ? JSON.parse(fs.readFileSync(output)).records : [];

async function main() {
  const temporary = path.join(root, '.work/simulation-20261028/browser-temp');
  fs.mkdirSync(temporary, {recursive: true});
  const browser = await chromium.launch({executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true, env: {...process.env, TMPDIR: temporary}});
  try {
    const page = await browser.newPage({locale: 'zh-CN', viewport: {width: 1440, height: 1024}});
    let pending = null;
    let authenticated = false;
    page.on('websocket', socket => {
      socket.on('framesent', frame => {
        const value = JSON.parse(frame.payload.toString());
        if (pending && value.type === 'message') pending.message = value;
      });
      socket.on('framereceived', frame => {
        const value = JSON.parse(frame.payload.toString());
        if (pending && value.event === 'turn_end' && value.turn_id === pending.message?.turn_id) pending.resolve(value);
      });
    });
    async function visit(id) {
      await page.goto(origin + '/?bossPage=' + id);
      if (!authenticated) {
        await page.getByLabel('账号', {exact: true}).fill(account.username);
        await page.getByLabel('密码', {exact: true}).fill(account.password);
        await page.getByRole('button', {name: '登录', exact: true}).click();
        authenticated = true;
      }
      await page.locator('.boss-v6[data-role="BOSS"]').waitFor();
    }
    async function send(question) {
      const input = page.locator('.boss-native-surface textarea:visible').last();
      await input.fill(question + ' 请用300字以内说明，并引用资料。');
      await input.press('Enter');
    }
    async function run(name, action) {
      if (requested.length && !requested.includes(name)) return;
      let timer;
      const completed = new Promise((resolve, reject) => {
        timer = setTimeout(() => reject(new Error(name + ' 没有完成实际 Agent 回答')), 330000);
        pending = {name, resolve, message: null};
      });
      try {
        await action();
        await completed;
        assert.ok(pending.message?.chat_id);
        const record = JSON.parse(execFileSync(path.join(root, 'validation/.venv/bin/python'),
          [path.join(root, 'scripts/inspect_simulation_run.py'), '--directory', directory, '--chat-id', pending.message.chat_id],
          {cwd: root, encoding: 'utf8'}));
        const text = await page.locator('.boss-native-surface').innerText();
        const excluded = String.fromCodePoint(28023, 22823, 38598, 22242);
        assert.equal(text.includes(excluded), false);
        const existing = records.findIndex(row => row.case === name);
        if (existing >= 0) records.splice(existing, 1);
        records.push({case: name, ...record, submitted_characters: pending.message.content.length, visual: 'NOT_RUN'});
        fs.writeFileSync(output, JSON.stringify({origin, records}, null, 2));
        console.log(JSON.stringify(records.at(-1)));
      } finally {clearTimeout(timer); pending = null;}
    }
    for (const title of ['安排今日工作', '了解经营情况', '跟进任务进展', '查看会议与资料']) {
      await run('suggestion-' + title, async () => {
        await visit('N02');
        await page.getByRole('button', {name: '新对话', exact: true}).click();
        await page.locator('.boss-chat-suggestions').getByRole('button', {name: new RegExp(title)}).click();
        await page.locator('.boss-native-surface textarea:visible').last().press('Enter');
      });
    }
    await run('morning-question', async () => {
      await visit('F01');
      await page.locator('#morning-question').fill('请整理今天需要本人决定和协调的事项，核查责任人和业务期限。');
      await page.locator('.boss-f01-entry-actions').getByRole('button', {name: '发送', exact: true}).click();
    });
    await run('business-question', async () => {
      await visit('N03');
      await page.locator('#overview-discuss').click();
    });
    for (const [use, title, metric] of [['EGG', '蛋禽', '产蛋量'], ['MILK', '奶畜', '产奶表现'], ['BEEF', '肉用牛羊', '生长表现']]) {
      await run('business-' + use + '-question', async () => {
        await visit('N03');
        await page.locator('#overview-topic-F19').click();
        await page.getByRole('button', {name: title, exact: true}).click();
        await page.locator('.boss-n03-dialog').getByText(metric, {exact: true}).waitFor();
        await page.locator('.boss-n03-dialog').getByRole('button', {name: '继续讨论', exact: true}).click();
      });
    }
    await run('meeting-discussion', async () => {
      await visit('N04');
      await page.locator('.boss-meeting-library tbody button').first().click();
      await page.getByRole('button', {name: '讨论这场会议', exact: true}).click();
    });
    await run('document-discussion', async () => {
      await visit('N04');
      await page.locator('.boss-meeting-library').getByRole('tab', {name: /资料/}).click();
      await page.getByPlaceholder('按名称搜索当前分类').fill('历史年度经营基准');
      await page.getByRole('button', {name: '筛选', exact: true}).click();
      await page.locator('.boss-meeting-library tbody button').first().click();
      await page.getByRole('button', {name: '让 Boss Agent 整理这份资料', exact: true}).click();
    });
    await run('research-question', async () => {
      await visit('F09');
      await page.getByRole('button', {name: '继续追问', exact: true}).click();
    });
    await run('task-question', async () => {
      await visit('N05');
      await page.locator('.boss-task-table-row').first().click();
      await page.getByRole('button', {name: '处理任务与结果', exact: true}).click();
      await page.getByRole('button', {name: '新建当前任务会话', exact: true}).click();
      await send('请读取绑定任务，说明目的、当前状态、反馈依据与本人下一步。');
    });
  } finally {await browser.close();}
}

main();
