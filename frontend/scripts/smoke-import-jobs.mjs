// Exercise the real store with deferred HTTP results and controlled polling timers.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const { createPinia, setActivePinia } = require('pinia')
const axios = require('axios')
const source = ts.transpileModule(readFileSync(new URL('../src/stores/teacher.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true }
}).outputText
let passed = 0

const job = (id, changes = {}) => ({
  id, subject: 'math', filename: '教材.pdf', status: 'running', stage: 'ocr', progress: 43,
  completed_pages: 70, total_pages: 168, message: '正在识别文字', document_id: null,
  vector_status: null, warnings: [], error: null,
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...changes
})

function fixture() {
  setActivePinia(createPinia())
  const auth = { user: { id: 1 }, role: 'teacher', token: 'test-only-token' }
  const reads = [], posts = [], timers = new Map()
  let timerId = 0
  function pending(url, config, payload) {
    let resolve, reject
    const promise = new Promise((yes, no) => { resolve = yes; reject = no })
    return { url, config, payload, promise, resolve, reject }
  }
  const api = {
    get(url, config) { const item = pending(url, config); reads.push(item); return item.promise },
    post(url, payload, config) { const item = pending(url, config, payload); posts.push(item); return item.promise }
  }
  const module = { exports: {} }
  vm.runInNewContext(source, {
    module, exports: module.exports, AbortController, FormData, Date,
    setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, delay }); return id },
    clearTimeout(id) { timers.delete(id) },
    require(name) {
      if (['pinia', 'vue', 'axios'].includes(name)) return require(name)
      if (name === '../api/client') return { __esModule: true, default: api }
      if (name === './auth') return { useAuthStore: () => auth }
      throw new Error(`Unexpected module: ${name}`)
    }
  })
  return { store: module.exports.useTeacherStore(), auth, reads, posts, timers }
}

async function flush() { for (let count = 0; count < 16; count++) await Promise.resolve() }
async function restore(f, jobs) {
  f.store.syncKnowledgeImportSession()
  f.reads[0].resolve({ data: { items: jobs } })
  await flush()
}

{
  const f = fixture()
  await restore(f, [job('resume')])
  assert.equal(f.store.knowledgeImportToasts[0].percent, 43)
  assert.equal(f.store.knowledgeImportToasts[0].detail, '70 / 168 页')
  assert.equal(f.store.knowledgeImportToasts[0].status, 'processing')
  const first = f.store.refreshKnowledgeImportJobs()
  const second = f.store.refreshKnowledgeImportJobs()
  assert.equal(f.reads.length, 2, 'focus and poll must share one status request')
  f.reads[1].resolve({ data: { items: [job('resume', { status: 'completed', progress: 100 })] } })
  await Promise.all([first, second])
  assert.equal(f.store.knowledgeImportToasts[0].status, 'success')
  assert.equal(f.store.knowledgeImportVersions.math, 1)
  assert.equal(f.timers.size, 0, 'completed tasks do not continue polling')
  passed++
}

{
  const f = fixture()
  await restore(f, [job('offline')])
  const request = f.store.refreshKnowledgeImportJobs()
  f.reads[1].reject(new Error('network offline'))
  await request
  assert.equal(f.store.knowledgeImportJobs[0].status, 'running')
  assert.equal(f.store.knowledgeImportToasts[0].percent, 43)
  assert.match(f.store.knowledgeImportToasts[0].detail, /重连/)
  assert.equal(f.timers.size, 1)
  passed++
}

{
  const f = fixture()
  f.store.syncKnowledgeImportSession()
  const oldRequest = f.reads[0]
  f.auth.user = { id: 2 }
  f.auth.token = 'another-test-only-token'
  f.store.syncKnowledgeImportSession()
  assert.equal(oldRequest.config.signal.aborted, true)
  oldRequest.resolve({ data: { items: [job('previous-account')] } })
  await flush()
  assert.equal(f.store.knowledgeImportJobs.length, 0)
  f.reads[1].resolve({ data: { items: [job('current-account')] } })
  await flush()
  assert.equal(f.store.knowledgeImportJobs[0].id, 'current-account')
  f.auth.token = ''
  f.store.syncKnowledgeImportSession()
  assert.equal(f.store.knowledgeImportToasts.length, 0)
  assert.equal(f.timers.size, 0)
  passed++
}

{
  const f = fixture()
  const file = new File(['pdf-content'], '教材.pdf', { type: 'application/pdf' })
  const upload = f.store.importSubjectKnowledgeDocument('math', file)
  await assert.rejects(f.store.importSubjectKnowledgeDocument('math', file), /正在上传/)
  assert.equal(f.posts.length, 1)
  f.posts[0].config.onUploadProgress({ loaded: 100, total: 100 })
  assert.equal(f.store.knowledgeImportToasts[0].status, 'uploading')
  assert.equal(f.store.knowledgeImportToasts[0].title, '正在确认上传')
  f.posts[0].resolve({ data: job('accepted', { status: 'queued', progress: 0 }) })
  await upload
  // The initial status request predates the accepted upload and must not erase it.
  f.reads[0].resolve({ data: { items: [] } })
  await flush()
  assert.equal(f.store.knowledgeImportJobs[0].id, 'accepted')
  assert.equal(f.store.knowledgeUploads.length, 0)
  assert.equal(f.store.knowledgeImportToasts[0].percent, 0)
  passed++
}

{
  const f = fixture()
  const failed = job('dismiss', { status: 'failed', error: '无法读取文件' })
  await restore(f, [failed])
  assert.equal(f.store.knowledgeImportToasts[0].canRetry, true)
  const snapshot = f.store.refreshKnowledgeImportJobs()
  const close = f.store.dismissKnowledgeImportToast('job:dismiss')
  assert.match(f.posts[0].url, /\/dismiss$/)
  f.posts[0].resolve({ data: {} })
  await close
  f.reads[1].resolve({ data: { items: [failed] } })
  await snapshot
  assert.equal(f.store.knowledgeImportToasts.length, 0, 'an older snapshot cannot restore a dismissed notice')
  const refreshed = fixture()
  await restore(refreshed, [])
  assert.equal(refreshed.store.knowledgeImportToasts.length, 0)
  passed++
}

{
  const f = fixture()
  const failed = job('retry', { status: 'failed' })
  await restore(f, [failed])
  const snapshot = f.store.refreshKnowledgeImportJobs()
  const retry = f.store.retryKnowledgeImport('retry')
  await f.store.retryKnowledgeImport('retry')
  assert.equal(f.posts.length, 1, 'retry double clicks are coalesced')
  f.posts[0].resolve({ data: job('retry', { status: 'queued', progress: 0 }) })
  await retry
  f.reads[1].resolve({ data: { items: [failed] } })
  await snapshot
  assert.equal(f.store.knowledgeImportJobs[0].status, 'queued')
  assert.equal(f.store.knowledgeImportToasts[0].canDismiss, false)
  passed++
}

{
  const f = fixture()
  await restore(f, [])
  const upload = assert.rejects(f.store.importSubjectKnowledgeDocument('math',
    new File(['pdf'], '教材.pdf', { type: 'application/pdf' })))
  f.posts[0].reject(new axios.AxiosError('timeout', 'ECONNABORTED'))
  await upload
  assert.equal(f.store.knowledgeImportToasts[0].status, 'waiting')
  const confirm = f.store.refreshKnowledgeImportJobs()
  f.reads[1].resolve({ data: { items: [job('received')] } })
  await confirm
  assert.equal(f.store.knowledgeUploads.length, 0)
  assert.equal(f.store.knowledgeImportToasts[0].status, 'processing')
  passed++
}

{
  const f = fixture()
  await restore(f, [job('math'), job('english', { subject: 'english' })])
  const request = f.store.refreshKnowledgeImportJobs()
  f.reads[1].resolve({ data: { items: [job('math', { status: 'completed' }), job('english', { subject: 'english' })] } })
  await request
  assert.equal(f.store.knowledgeImportVersions.math, 1)
  assert.equal(f.store.knowledgeImportVersions.english, undefined)
  assert.equal(f.store.knowledgeImportToasts.length, 2)
  passed++
}

console.log(`Import job state: ${passed} cases passed`)
