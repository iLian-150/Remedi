// Real Pinia stores with deferred API responses; no browser or server is used.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const { createPinia, setActivePinia } = require('pinia')
const { watch, nextTick } = require('vue')
const auth = { user: { id: 1 }, token: 'test-only-token' }
const storage = new Map()
const localStorage = {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: key => storage.delete(key)
}
let passed = 0

function deferred() {
  let yes, no
  const promise = new Promise((resolve, reject) => { yes = resolve; no = reject })
  const timer = setTimeout(() => no(new Error('Mock response was not completed within 3 seconds')), 3000)
  const resolve = value => { clearTimeout(timer); yes(value) }
  const reject = error => { clearTimeout(timer); no(error) }
  return { promise, resolve, reject }
}

function fixture(kind) {
  setActivePinia(createPinia())
  auth.user = { id: 1 }
  storage.clear()
  const pending = []
  const reads = []
  const errors = []
  const api = {
    post: () => { const request = deferred(); pending.push(request); return request.promise },
    delete: () => { const request = deferred(); pending.push(request); return request.promise },
    get: (url, config) => {
      const request = { ...deferred(), url, config }
      reads.push(request)
      return request.promise
    }
  }
  const filename = fileURLToPath(new URL(`../src/stores/${kind}.ts`, import.meta.url))
  const source = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true }
  }).outputText
  const module = { exports: {} }
  vm.runInNewContext(source, {
    module, exports: module.exports, localStorage, console: { ...console, error: (...args) => errors.push(args) },
    require: name => {
      if (name === 'pinia') return require('pinia')
      if (name === 'vue') return require('vue')
      if (name === 'axios') return require('axios')
      if (name === '../api/client') return { __esModule: true, default: api }
      if (name === './auth') return { useAuthStore: () => auth }
      if (name === '../utils/visionImage') return { visionImageForModel: () => { throw new Error('Unexpected image request') } }
      throw new Error(`Unexpected module: ${name}`)
    }
  }, { filename })
  const useStore = module.exports[kind === 'student' ? 'useStudentStore' : 'useTeacherStore']
  return { store: useStore(), pending, reads, errors }
}

const session = id => ({ id, title: 'Test session', message_count: 0, updated_at: '2026-10-23T00:00:00' })
const cancelled = promise => assert.rejects(promise, error => error.name === 'AbortError')
const page = (items, hasMore = false) => ({
  items, has_more: hasMore,
  before_updated_at: hasMore ? items.at(-1).updated_at : null,
  before_id: hasMore ? items.at(-1).id : null
})
const ids = store => Array.from(store.sessions, item => item.id)
// Flush a bounded number of Promise continuations, including Pinia action wrappers.
async function flush() { for (let count = 0; count < 16; count++) await Promise.resolve() }

for (const kind of ['student', 'teacher']) {
  {
    const { store, pending } = fixture(kind)
    const first = store.startSidebarSession()
    const second = store.startSidebarSession()
    assert.equal(pending.length, 1)
    pending[0].resolve({ data: session(10) })
    assert.equal((await first).id, 10)
    assert.equal((await second).id, 10)
    assert.equal(store.sessions.length, 1)
    assert.equal(store.sessionCreatePromise, null)
    assert.equal(store.sessionView.seq, 1)
    assert.equal((await store.startSidebarSession()).id, 10)
    assert.equal(pending.length, 1)
    passed++
  }
  {
    const { store, pending } = fixture(kind)
    const result = cancelled(store.startSidebarSession())
    store.clearSessionState()
    pending[0].resolve({ data: session(777) })
    await result
    assert.equal(store.sessions.length, 0)
    assert.equal(store.activeSessionId, null)
    assert.equal(storage.has('remedi_student_active_session_1'), false)
    passed++
  }
  {
    const { store, pending } = fixture(kind)
    const result = cancelled(store.startSidebarSession())
    auth.user = { id: 2 }
    pending[0].resolve({ data: session(777) })
    await result
    assert.equal(store.sessions.length, 0)
    assert.equal(storage.has('remedi_student_active_session_2'), false)
    passed++
  }
  {
    const { store, pending } = fixture(kind)
    const old = cancelled(store.startSidebarSession())
    store.clearSessionState()
    const fresh = store.startSidebarSession()
    pending[0].resolve({ data: session(777) })
    await old
    assert.notEqual(store.sessionCreatePromise, null)
    const duplicate = store.startSidebarSession()
    assert.equal(pending.length, 2)
    pending[1].resolve({ data: session(888) })
    await Promise.all([fresh, duplicate])
    assert.deepEqual(Array.from(store.sessions, item => item.id), [888])
    passed++
  }
  {
    const { store, pending } = fixture(kind)
    const first = assert.rejects(store.startSidebarSession(), /temporary failure/)
    pending[0].reject(new Error('temporary failure'))
    await first
    assert.equal(store.sessionCreatePromise, null)
    const retry = store.startSidebarSession()
    pending[1].resolve({ data: session(30) })
    assert.equal((await retry).id, 30)
    passed++
  }
  {
    const { store, pending } = fixture(kind)
    store.sessions = [session(50)]
    store.activeSessionId = 50
    const deletion = store.removeSidebarSession(50)
    store.clearSessionState()
    auth.user = { id: 2 }
    store.sessions = [session(50)]
    store.activeSessionId = 50
    pending[0].resolve({})
    await deletion
    assert.equal(store.activeSessionId, 50)
    assert.equal(store.sessions.length, 1)
    assert.equal(store.sessionView.seq, 0)
    passed++
  }
  {
    const { store, pending } = fixture(kind)
    store.sessions = [session(50), session(60)]
    store.activeSessionId = 50
    const deletion = store.removeSidebarSession(50)
    pending[0].resolve({})
    await deletion
    assert.deepEqual(Array.from(store.sessions, item => item.id), [60])
    assert.equal(store.activeSessionId, 60)
    passed++
  }
}

{
  const { store, pending } = fixture('student')
  const load = deferred()
  store.loadSessions = () => load.promise
  const result = cancelled(store.ensureActiveChatSession())
  store.clearSessionState()
  load.resolve()
  await result
  assert.equal(pending.length, 0)
  passed++
}
{
  const { store, pending } = fixture('student')
  store.sessionsLoaded = true
  const result = cancelled(store.ensureActiveChatSession())
  store.clearSessionState()
  auth.user = { id: 2 }
  pending[0].resolve({ data: session(777) })
  await result
  assert.equal(store.sessions.length, 0)
  assert.equal(storage.has('remedi_student_active_session_2'), false)
  passed++
}

for (const kind of ['student', 'teacher']) {
  // Stable first-page, explicit refresh and pagination retain their normal behavior.
  {
    const { store, reads } = fixture(kind)
    const first = store.loadSessions()
    const duplicate = store.loadSessions()
    assert.equal(reads.length, 1)
    reads[0].resolve({ data: page([session(20), session(10)], true) })
    await Promise.all([first, duplicate])
    assert.equal(store.activeSessionId, 20)
    assert.equal(store.sessionsCursor.before_id, 10)
    const refresh = store.loadSessions(true)
    assert.equal(reads[1].config.params.include_id, 20)
    reads[1].resolve({ data: page([session(30), session(20)], true) })
    await refresh
    const more = store.loadMoreSessions()
    assert.equal(reads[2].config.params.before_id, 20)
    reads[2].resolve({ data: page([session(20), session(10)]) })
    await more
    assert.deepEqual(ids(store), [30, 20, 10])
    assert.equal(store.activeSessionId, 20)
    assert.equal(store.sessionsHasMore, false)
    assert.equal(store.sessionsCursor, null)
    assert.equal(store.sessionsMutationVersion, 0)
    passed++
  }
  // A stale first page must retry within the same shared load and restore history.
  {
    const { store, pending, reads } = fixture(kind)
    const loading = store.loadSessions()
    const shared = store.loadSessions()
    const creating = store.startSidebarSession()
    pending[0].resolve({ data: session(50) })
    await creating
    reads[0].resolve({ data: page([session(10)]) })
    await flush()
    assert.equal(reads.length, 2)
    assert.deepEqual(ids(store), [50])
    assert.equal(store.activeSessionId, 50)
    assert.equal(store.sessionsLoading, true)
    assert.equal(reads[1].config.params.include_id, 50)
    reads[1].resolve({ data: page([session(50), session(10), session(5)], true) })
    await Promise.all([loading, shared])
    assert.deepEqual(ids(store), [50, 10, 5])
    assert.equal(store.sessionsCursor.before_id, 5)
    assert.equal(store.sessionsLoaded, true)
    assert.equal(store.sessionsLoading, false)
    assert.equal(store.sessionsMutationVersion, 1)
    passed++
  }
  {
    const { store, pending, reads } = fixture(kind)
    store.sessions = [session(50), session(40)]
    store.activeSessionId = 50
    const loading = store.loadSessions()
    const deleting = store.removeSidebarSession(50)
    pending[0].resolve({})
    await deleting
    reads[0].resolve({ data: page([session(50), session(40)]) })
    await flush()
    assert.equal(reads.length, 2)
    assert.deepEqual(ids(store), [40])
    assert.equal(store.activeSessionId, 40)
    reads[1].resolve({ data: page([session(40), session(30)]) })
    await loading
    assert.deepEqual(ids(store), [40, 30])
    assert.equal(store.sessionView.id, 40)
    assert.equal(store.sessionsMutationVersion, 1)
    passed++
  }
  // A late older page cannot resurrect a deleted row or overwrite a new session.
  for (const operation of ['delete', 'create']) {
    const { store, pending, reads } = fixture(kind)
    store.sessions = [session(60), session(50)]
    store.activeSessionId = 60
    store.sessionsLoaded = true
    store.sessionsHasMore = true
    store.sessionsCursor = { before_updated_at: session(50).updated_at, before_id: 50 }
    if (operation === 'create') store.sessions[0].message_count = 1
    const loading = store.loadMoreSessions()
    const changing = operation === 'delete' ? store.removeSidebarSession(50) : store.startSidebarSession()
    assert.equal(pending.length, 1)
    pending[0].resolve(operation === 'delete' ? {} : { data: session(70) })
    await changing
    reads[0].resolve({ data: page([session(50), session(40)], true) })
    await flush()
    assert.equal(reads.length, 2)
    assert.equal(reads[1].config.params.before_id, 50)
    assert.deepEqual(ids(store), operation === 'delete' ? [60] : [70, 60, 50])
    reads[1].resolve({ data: page([session(40), session(30)]) })
    await loading
    assert.deepEqual(ids(store), operation === 'delete' ? [60, 40, 30] : [70, 60, 50, 40, 30])
    assert.equal(store.sessionsPageLoading, false)
    assert.equal(store.sessionsHasMore, false)
    passed++
  }
  // A queued force refresh shares retries, then still fetches a fresh snapshot itself.
  {
    const { store, pending, reads } = fixture(kind)
    const loading = store.loadSessions()
    const refresh = store.loadSessions(true)
    const duplicateRefresh = store.loadSessions(true)
    const creating = store.startSidebarSession()
    pending[0].resolve({ data: session(70) })
    await creating
    reads[0].resolve({ data: page([session(10)]) })
    await flush()
    assert.equal(reads.length, 2)
    reads[1].resolve({ data: page([session(70), session(10)]) })
    await flush()
    assert.equal(reads.length, 3)
    const deleting = store.removeSidebarSession(10)
    pending[1].resolve({})
    await deleting
    reads[2].resolve({ data: page([session(70), session(10)]) })
    await flush()
    assert.equal(reads.length, 4)
    assert.deepEqual(ids(store), [70])
    reads[3].resolve({ data: page([session(70), session(60)]) })
    await Promise.all([loading, refresh, duplicateRefresh])
    assert.deepEqual(ids(store), [70, 60])
    assert.equal(store.sessionsRefreshPromise, null)
    passed++
  }
  // Generation or owner invalidation stops a stale request without retrying as a new user.
  for (const invalidation of ['generation', 'owner']) {
    const { store, pending, reads } = fixture(kind)
    const loading = store.loadSessions()
    const queuedRefresh = store.loadSessions(true)
    const creating = store.startSidebarSession()
    pending[0].resolve({ data: session(70) })
    await creating
    if (invalidation === 'generation') store.clearSessionState()
    else auth.user = { id: 2 }
    const expected = ids(store)
    reads[0].resolve({ data: page([session(10)]) })
    await Promise.all([loading, queuedRefresh])
    assert.equal(reads.length, 1)
    assert.deepEqual(ids(store), expected)
    passed++
  }
  // Retrying is bounded and visibly recoverable, rather than silently keeping an incomplete list.
  {
    const { store, pending, reads, errors } = fixture(kind)
    store.sessions = [session(70), session(60), session(50)]
    store.activeSessionId = 70
    const loading = store.loadSessions()
    for (let index = 0; index < 3; index++) {
      const deleting = store.removeSidebarSession(70 - index * 10)
      pending[index].resolve({})
      await deleting
      reads[index].resolve({ data: page([session(70), session(60), session(50)]) })
      await flush()
    }
    await loading
    assert.equal(reads.length, 3)
    assert.deepEqual(ids(store), [])
    assert.ok(store.sessionsError)
    assert.equal(errors.length, 1)
    assert.equal(store.sessionsLoading, false)
    const retry = store.loadSessions(true)
    reads[3].resolve({ data: page([session(90)]) })
    await retry
    assert.deepEqual(ids(store), [90])
    assert.equal(store.sessionsError, '')
    passed++
  }
  // The GET included the old active ID; selecting an older loaded row must remain authoritative.
  {
    const { store, reads } = fixture(kind)
    store.sessions = [session(70), session(60), session(10)]
    store.activeSessionId = 70
    store.sessionsLoaded = true
    const loading = store.loadSessions(true)
    assert.equal(reads[0].config.params.include_id, 70)
    store.selectSidebarSession(10)
    const viewSeq = store.sessionView.seq
    reads[0].resolve({ data: page([session(70), session(60)], true) })
    await loading
    assert.deepEqual(ids(store), [70, 60, 10])
    assert.equal(store.activeSessionId, 10)
    assert.equal(store.sessionView.id, 10)
    assert.equal(store.sessionView.seq, viewSeq)
    assert.equal(store.sessionsCursor.before_id, 60)
    if (kind === 'student') assert.equal(await store.ensureActiveChatSession(), 10)
    passed++
  }
}

// Concurrent first sends share both the initial load and the actual creation.
for (const initiallyLoaded of [true, false]) {
  const { store, pending, reads } = fixture('student')
  store.sessionsLoaded = initiallyLoaded
  const first = store.ensureActiveChatSession()
  const second = store.ensureActiveChatSession()
  if (!initiallyLoaded) {
    assert.equal(reads.length, 1)
    reads[0].resolve({ data: page([]) })
    await flush()
  }
  assert.equal(pending.length, 1)
  pending[0].resolve({ data: session(50) })
  assert.deepEqual(await Promise.all([first, second]), [50, 50])
  assert.deepEqual(ids(store), [50])
  assert.equal(store.sessionsMutationVersion, 1)
  assert.equal(store.sessionView.seq, 0)
  assert.equal(store.sessionCreatePromise, null)
  passed++
}

for (const sidebarFirst of [true, false]) {
  for (const initiallyLoaded of [true, false]) {
    const { store, pending, reads } = fixture('student')
    store.sessionsLoaded = initiallyLoaded
    const ui = { messages: ['user question', 'pending response'], image: 'selected photo', sending: true }
    // StudentChat's seq watcher clears conversation messages and the selected image.
    const stop = watch(() => store.sessionView.seq, () => { ui.messages = []; ui.image = '' })
    const sidebar = sidebarFirst ? store.startSidebarSession() : null
    const sending = store.ensureActiveChatSession()
    const joinedSidebar = sidebar ?? store.startSidebarSession()
    if (!initiallyLoaded && !sidebarFirst) {
      assert.equal(reads.length, 1)
      reads[0].resolve({ data: page([]) })
      await flush()
    }
    assert.equal(pending.length, 1)
    pending[0].resolve({ data: session(50) })
    if (!initiallyLoaded && sidebarFirst) {
      await flush()
      assert.equal(reads.length, 1)
      reads[0].resolve({ data: page([session(50), session(10)]) })
    }
    assert.equal(await sending, 50)
    assert.equal((await joinedSidebar).id, 50)
    await nextTick()
    assert.deepEqual(ids(store), !initiallyLoaded && sidebarFirst ? [50, 10] : [50])
    assert.equal(store.activeSessionId, 50)
    assert.equal(store.sessionView.seq, 0)
    assert.deepEqual(ui, { messages: ['user question', 'pending response'], image: 'selected photo', sending: true })
    assert.equal(storage.get('remedi_student_active_session_1'), '50')
    stop()
    passed++
  }
}

console.log(`PASS: ${passed} session lifecycle checks`)
