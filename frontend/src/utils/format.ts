const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function formatDate(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '-' : dateFormatter.format(date)
}

export function formatDuration(startedAt: string, finishedAt: string | null): string {
  if (!finishedAt) return '执行中'
  const duration = new Date(finishedAt).valueOf() - new Date(startedAt).valueOf()
  if (!Number.isFinite(duration) || duration < 0) return '-'
  if (duration < 1000) return `${duration} ms`
  if (duration < 60_000) return `${(duration / 1000).toFixed(1)} s`
  return `${Math.floor(duration / 60_000)}m ${Math.round((duration % 60_000) / 1000)}s`
}

export function truncate(value: string, limit = 70): string {
  return value.length > limit ? `${value.slice(0, limit)}...` : value
}
