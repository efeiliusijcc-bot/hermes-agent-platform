import rawGuide from './platformAdminGuide.json'

export type GuideSectionId = 'models' | 'runtimes' | 'connections' | 'database' | 'api' | 'operations' | 'settings'

export interface GuideField { name: string; meaning: string; recommendation: string }
export interface GuideError { symptom: string; cause: string; solution: string }
export interface GuideSection {
  id: GuideSectionId
  title: string
  menuPath: string
  purpose: string
  prerequisites: string[]
  fields: GuideField[]
  steps: string[]
  success: string[]
  errors: GuideError[]
  security: string[]
}

export interface PlatformAdminGuide {
  title: string
  description: string
  updated: string
  recommendedOrder: Array<{ title: string; detail: string; section: GuideSectionId }>
  glossary: Array<{ term: string; definition: string }>
  statuses: Array<{ status: string; meaning: string; action: string }>
  sections: GuideSection[]
  scenarios: Array<{ title: string; steps: string[] }>
}

export const platformAdminGuide = rawGuide as PlatformAdminGuide

function bulletList(items: string[]): string {
  return items.map((item) => `- ${item}`).join('\n')
}

function numberedList(items: string[]): string {
  return items.map((item, index) => `${index + 1}. ${item}`).join('\n')
}

function table(headers: string[], rows: string[][]): string {
  const sanitize = (value: string) => value.replaceAll('|', '\\|').replaceAll('\n', '<br>')
  return [
    `| ${headers.map(sanitize).join(' | ')} |`,
    `| ${headers.map(() => '---').join(' | ')} |`,
    ...rows.map((row) => `| ${row.map(sanitize).join(' | ')} |`),
  ].join('\n')
}

export function renderPlatformAdminGuideMarkdown(guide: PlatformAdminGuide = platformAdminGuide): string {
  const blocks = [
    `# ${guide.title}`,
    guide.description,
    `更新日期：${guide.updated}`,
    '## 首次配置推荐顺序',
    numberedList(guide.recommendedOrder.map((item) => `**${item.title}**：${item.detail}`)),
    '## 统一术语表',
    table(['术语', '通俗解释'], guide.glossary.map((item) => [item.term, item.definition])),
    '## 状态说明',
    table(['状态', '含义', '建议操作'], guide.statuses.map((item) => [item.status, item.meaning, item.action])),
  ]

  for (const section of guide.sections) {
    blocks.push(
      `## ${section.title}`,
      `菜单路径：${section.menuPath}`,
      '### 用途',
      section.purpose,
      '### 使用前准备',
      bulletList(section.prerequisites),
      '### 字段说明',
      table(['字段', '含义', '推荐配置'], section.fields.map((item) => [item.name, item.meaning, item.recommendation])),
      '### 操作步骤',
      numberedList(section.steps),
      '### 成功标准',
      bulletList(section.success),
      '### 常见错误',
      table(['现象', '常见原因', '处理方法'], section.errors.map((item) => [item.symptom, item.cause, item.solution])),
      '### 安全注意事项',
      bulletList(section.security),
    )
  }

  blocks.push(
    '## 常见场景',
    ...guide.scenarios.flatMap((scenario) => [`### ${scenario.title}`, numberedList(scenario.steps)]),
    '## 故障定位顺序',
    numberedList([
      '先确认输入、Agent 生命周期和 Preflight 结果。',
      '检查 Operations 中的基础设施和 Runtime Health。',
      '打开 Execution 详情确认失败节点和标准错误码。',
      '查看 Trace 中的模型、Capability、Connector、Scope 和 Artifact 事件。',
      '从实际调用容器验证 DNS、端口和目标服务健康。',
      '使用相同最小输入复测，并保留修复前后的 Execution ID。',
    ]),
    '## 安全边界总览',
    bulletList([
      '浏览器和模型都不能读取明文模型 Key、数据库密码或 Connector Credential。',
      '模型只能提交业务参数，不能选择 Endpoint、Credential、Implementation 或 Scope。',
      'Revision、Scope Revision、Schema Version 和已发布 Capability Version 不可原地覆盖。',
      'Docker 网络、主密钥、内部服务密钥和宿主机配置由部署人员维护。',
      '完全隔离内网不代表可以取消最小权限、只读 SQL、配额、审计和 Agent 隔离。',
    ]),
  )

  return `${blocks.join('\n\n')}\n`
}

export function guideSearchText(section: GuideSection): string {
  return [
    section.title,
    section.menuPath,
    section.purpose,
    ...section.prerequisites,
    ...section.fields.flatMap((field) => [field.name, field.meaning, field.recommendation]),
    ...section.steps,
    ...section.success,
    ...section.errors.flatMap((error) => [error.symptom, error.cause, error.solution]),
    ...section.security,
  ].join(' ').toLocaleLowerCase('zh-CN')
}
