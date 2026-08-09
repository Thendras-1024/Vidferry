export const mergeAndSortAgentSessions = (sessions = [], metadata = {}) => sessions
  .map(session => ({ ...session, ...(metadata[session.id] || {}) }))
  .sort((left, right) => {
    if (Boolean(left.isPinned) !== Boolean(right.isPinned)) return left.isPinned ? -1 : 1
    const leftTime = Date.parse(left.isPinned ? left.pinnedAt : left.updatedAt) || 0
    const rightTime = Date.parse(right.isPinned ? right.pinnedAt : right.updatedAt) || 0
    return rightTime - leftTime
  })
