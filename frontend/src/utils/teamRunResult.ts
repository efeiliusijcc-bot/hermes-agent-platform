export interface TeamRunResultPresentation {
  raw: string
  structured: unknown | null
  structuredText: string
  readable: string
  reportMarkdown: string | null
  businessStatus: string | null
  title: string | null
  summary: string | null
  blockingReasons: string[]
  informationGaps: string[]
}

type JsonRecord = Record<string, unknown>

function asRecord(value: unknown): JsonRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : null
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
    .map((item) => item.trim())
}

function parseJson(value: string): unknown | null {
  const trimmed = value.trim()
  if (!trimmed) return null

  const candidates = [trimmed]
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i)
  if (fenced?.[1]) candidates.push(fenced[1])

  const firstBrace = trimmed.indexOf('{')
  const lastBrace = trimmed.lastIndexOf('}')
  if (firstBrace >= 0 && lastBrace > firstBrace) candidates.push(trimmed.slice(firstBrace, lastBrace + 1))

  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate)
    } catch {
      // Try the next safe display candidate.
    }
  }
  return null
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function readableFallback(
  raw: string,
  structured: unknown | null,
  summary: string | null,
  blockingReasons: string[],
  informationGaps: string[],
): string {
  const sections: string[] = []
  if (summary) sections.push(`## 结果摘要\n${summary}`)
  if (blockingReasons.length) {
    sections.push(`## 阻塞原因\n${blockingReasons.map((item) => `- ${item}`).join('\n')}`)
  }
  if (informationGaps.length) {
    sections.push(`## 信息缺口\n${informationGaps.map((item) => `- ${item}`).join('\n')}`)
  }
  if (sections.length) return sections.join('\n\n')
  if (structured !== null) return `\`\`\`json\n${formatJson(structured)}\n\`\`\``
  if (raw.trim()) return raw
  return ''
}

export function presentTeamRunResult(
  output: string | null | undefined,
  outputJson: unknown | null | undefined = null,
): TeamRunResultPresentation {
  const raw = output || ''
  const structured = outputJson !== null && outputJson !== undefined
    ? outputJson
    : parseJson(raw)
  const record = asRecord(structured)
  const reportMarkdown = stringValue(record?.report_markdown)
  const businessStatus = stringValue(record?.status)
  const title = stringValue(record?.title)
  const summary = stringValue(record?.summary)
  const blockingReasons = stringList(record?.blocking_reasons)
  const informationGaps = stringList(record?.information_gaps)

  return {
    raw,
    structured,
    structuredText: structured === null ? '' : formatJson(structured),
    readable: reportMarkdown || readableFallback(
      raw,
      structured,
      summary,
      blockingReasons,
      informationGaps,
    ),
    reportMarkdown,
    businessStatus,
    title,
    summary,
    blockingReasons,
    informationGaps,
  }
}
