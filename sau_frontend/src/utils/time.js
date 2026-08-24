const BEIJING_TIME_ZONE = 'Asia/Shanghai'

export const parseBackendTime = value => {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  let text = String(value).trim()
  if (!text) return null
  const hasTimeZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(text)
  if (/^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$/.test(text)) {
    text = text.replace(' ', 'T') + (hasTimeZone ? '' : '+08:00')
  }
  const date = new Date(text)
  return Number.isNaN(date.getTime()) ? null : date
}

export const formatBeijingTime = (value, options = {}) => {
  const date = parseBackendTime(value)
  if (!date) return value ? String(value) : ''
  return date.toLocaleString('zh-CN', { timeZone: BEIJING_TIME_ZONE, hour12: false, ...options })
}

export const backendTimeMs = value => parseBackendTime(value)?.getTime() ?? Number.NaN
