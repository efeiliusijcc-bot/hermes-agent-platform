import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../..', import.meta.url))
const guide = JSON.parse(await readFile(new URL('../src/content/platformAdminGuide.json', import.meta.url), 'utf8'))

const bullets = (items) => items.map((item) => `- ${item}`).join('\n')
const numbered = (items) => items.map((item, index) => `${index + 1}. ${item}`).join('\n')
const table = (headers, rows) => {
  const sanitize = (value) => value.replaceAll('|', '\\|').replaceAll('\n', '<br>')
  return [
    `| ${headers.map(sanitize).join(' | ')} |`,
    `| ${headers.map(() => '---').join(' | ')} |`,
    ...rows.map((row) => `| ${row.map(sanitize).join(' | ')} |`),
  ].join('\n')
}

const blocks = [
  `# ${guide.title}`,
  guide.description,
  `更新日期：${guide.updated}`,
  '## 首次配置推荐顺序',
  numbered(guide.recommendedOrder.map((item) => `**${item.title}**：${item.detail}`)),
  '## 统一术语表',
  table(['术语', '通俗解释'], guide.glossary.map((item) => [item.term, item.definition])),
  '## 状态说明',
  table(['状态', '含义', '建议操作'], guide.statuses.map((item) => [item.status, item.meaning, item.action])),
]

for (const section of guide.sections) {
  blocks.push(
    `## ${section.title}`,
    `菜单路径：${section.menuPath}`,
    '### 用途', section.purpose,
    '### 使用前准备', bullets(section.prerequisites),
    '### 字段说明', table(['字段', '含义', '推荐配置'], section.fields.map((item) => [item.name, item.meaning, item.recommendation])),
    '### 操作步骤', numbered(section.steps),
    '### 成功标准', bullets(section.success),
    '### 常见错误', table(['现象', '常见原因', '处理方法'], section.errors.map((item) => [item.symptom, item.cause, item.solution])),
    '### 安全注意事项', bullets(section.security),
  )
}

blocks.push(
  '## 常见场景',
  ...guide.scenarios.flatMap((scenario) => [`### ${scenario.title}`, numbered(scenario.steps)]),
  '## 故障定位顺序',
  numbered([
    '先确认输入、Agent 生命周期和 Preflight 结果。',
    '检查 Operations 中的基础设施和 Runtime Health。',
    '打开 Execution 详情确认失败节点和标准错误码。',
    '查看 Trace 中的模型、Capability、Connector、Scope 和 Artifact 事件。',
    '从实际调用容器验证 DNS、端口和目标服务健康。',
    '使用相同最小输入复测，并保留修复前后的 Execution ID。',
  ]),
  '## 安全边界总览',
  bullets([
    '浏览器和模型都不能读取明文模型 Key、数据库密码或 Connector Credential。',
    '模型只能提交业务参数，不能选择 Endpoint、Credential、Implementation 或 Scope。',
    'Revision、Scope Revision、Schema Version 和已发布 Capability Version 不可原地覆盖。',
    'Docker 网络、主密钥、内部服务密钥和宿主机配置由部署人员维护。',
    '完全隔离内网不代表可以取消最小权限、只读 SQL、配额、审计和 Agent 隔离。',
  ]),
)

await writeFile(`${root}/docs/Hermes_Agent_Platform_Administration_Guide_CN.md`, `${blocks.join('\n\n')}\n`)
