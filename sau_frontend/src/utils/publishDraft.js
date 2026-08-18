export const cleanTopicList = (topics = []) => {
  const values = Array.isArray(topics) ? topics : String(topics || '').split(/[,，\s]+/)
  return Array.from(new Set(
    values
      .map(tag => String(tag || '').trim().replace(/^#+/, ''))
      .filter(Boolean)
  ))
}

export const normalizeDraftTopics = (draft) => {
  if (!draft) return
  draft.tags = cleanTopicList(draft.tags)
  draft.customTags = cleanTopicList(draft.customTags).filter(tag => !draft.tags.includes(tag))
  draft.tagOptions = Array.from(new Set([...draft.tags, ...cleanTopicList(draft.tagOptions)]))
}
