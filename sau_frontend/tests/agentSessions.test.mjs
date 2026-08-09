import assert from 'node:assert/strict'
import { mergeAndSortAgentSessions } from '../src/utils/agentSessions.js'

const sessions = [
  { id: 'old', updatedAt: '2026-08-01T00:00:00Z' },
  { id: 'new', updatedAt: '2026-08-03T00:00:00Z' },
  { id: 'first-pin', updatedAt: '2026-08-02T00:00:00Z' },
  { id: 'last-pin', updatedAt: '2026-07-30T00:00:00Z' }
]
const metadata = {
  'first-pin': { isPinned: true, pinnedAt: '2026-08-04T00:00:00Z' },
  'last-pin': { isPinned: true, pinnedAt: '2026-08-05T00:00:00Z', title: '置顶会话' }
}

const sorted = mergeAndSortAgentSessions(sessions, metadata)
assert.deepEqual(sorted.map(item => item.id), ['last-pin', 'first-pin', 'new', 'old'])
assert.equal(sorted[0].title, '置顶会话')
