import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const appSource = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')

assert.match(
  appSource,
  /const initializeAuthenticatedWorkspace = \(\) => \{\s*if \(authenticatedWorkspaceStarted \|\| !userStore\.isLoggedIn\) return\s*authenticatedWorkspaceStarted = true\s*void openAgentWorkbench\(\)/s
)
assert.match(appSource, /watch\(\(\) => userStore\.isLoggedIn, initializeAuthenticatedWorkspace\)/)
assert.match(appSource, /onMounted\(\(\) => \{\s*window\.addEventListener[\s\S]*?initializeAuthenticatedWorkspace\(\)/)
