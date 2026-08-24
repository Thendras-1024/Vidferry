const LEGACY_WORKSPACE_KEYS = [
  'vidferry:agent-session-id',
  'vidferry:agent-session-meta',
  'vidferry:publish-center:draft:v1',
  'vidferry:youtube.workflowSettings'
]

const workspaceUserId = userId => {
  const value = Number(userId || 0)
  return Number.isInteger(value) && value > 0 ? value : 0
}

export const userWorkspaceStorageKey = (userId, name) => {
  const ownerId = workspaceUserId(userId)
  return ownerId ? `vidferry:user:${ownerId}:${name}` : ''
}

export const removeLegacyWorkspaceStorage = () => {
  LEGACY_WORKSPACE_KEYS.forEach(key => localStorage.removeItem(key))
}

export const clearUserWorkspaceStorage = userId => {
  LEGACY_WORKSPACE_KEYS.forEach(key => {
    const scopedKey = userWorkspaceStorageKey(userId, key.slice('vidferry:'.length))
    if (scopedKey) localStorage.removeItem(scopedKey)
  })
}
