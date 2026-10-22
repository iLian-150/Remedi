// Run with: node smoke_auth.cjs. Uses existing TypeScript, Vue and Pinia dependencies.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')
const ts = require('typescript')
const pinia = require('pinia')
const vue = require('vue')
const axios = require('axios')

function compile(source) {
  return ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
  }).outputText
}

function makeStorage(initial = {}, failures = {}) {
  const values = new Map(Object.entries(initial))
  let writes = 0
  return {
    values,
    getItem(key) {
      if (failures.read) throw new Error('storage unavailable')
      return values.get(key) ?? null
    },
    setItem(key, value) {
      writes += 1
      if (failures.write || failures.failWriteAt === writes) throw new Error('storage unavailable')
      values.set(key, String(value))
    },
    removeItem(key) {
      if (failures.remove) throw new Error('storage unavailable')
      values.delete(key)
    }
  }
}

const authCode = compile(fs.readFileSync(path.join(__dirname, 'src/stores/auth.ts'), 'utf8'))
const student = { id: 1, name: '同学甲', role: 'student', student_no: 'S001' }
const teacher = { id: 2, name: '教师甲', role: 'teacher', student_no: null }

function loadAuth(storage) {
  const context = { exports: {}, require, localStorage: storage }
  vm.runInNewContext(authCode, context)
  pinia.setActivePinia(pinia.createPinia())
  return context.exports.useAuthStore()
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function loadLogin(post) {
  const source = fs.readFileSync(path.join(__dirname, 'src/views/RoleSelect.vue'), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  const sessions = [], redirects = [], requests = []
  const context = {
    exports: {},
    console: { error() {} },
    require(id) {
      if (id === 'vue') return vue
      if (id === 'vue-router') return { useRouter: () => ({ push: to => redirects.push(to) }) }
      if (id === '../stores/auth') return { useAuthStore: () => ({ setSession: (...args) => sessions.push(args) }) }
      if (id === '../api/client') return { default: { post: (url, payload) => {
        requests.push({ url, payload })
        return post(url, payload)
      } } }
      throw new Error(`unexpected import: ${id}`)
    }
  }
  vm.runInNewContext(compile(source + '\nglobalThis.state = { login, switchRole, role, username, studentNo, teacherSubject, loading, error };'), context)
  return { state: context.state, sessions, redirects, requests }
}

function loadClient(token) {
  const auth = { token, logoutCount: 0, logout() { this.token = ''; this.logoutCount += 1 } }
  const location = { pathname: '/teacher/agents', href: 'unchanged' }
  const source = fs.readFileSync(path.join(__dirname, 'src/api/client.ts'), 'utf8')
    .replace(/import\.meta\.env\.VITE_API_BASE_URL/g, "''")
  const context = {
    exports: {}, window: { location },
    require: id => id === 'axios' ? axios : { useAuthStore: () => auth }
  }
  vm.runInNewContext(compile(source), context)
  return { api: context.exports.default, auth, location }
}

function rejectUnauthorized(config) {
  throw new axios.AxiosError('unauthorized', 'ERR_BAD_REQUEST', config, null, {
    status: 401, statusText: 'Unauthorized', data: {}, headers: {}, config
  })
}

test('corrupt and incomplete persisted sessions recover without blocking login', () => {
  for (const cached of [
    { remedi_token: 'mock-1', remedi_user: '{broken-json' },
    { remedi_token: 'mock-1' },
    { remedi_user: JSON.stringify(student) },
    { remedi_token: 'mock-1', remedi_user: 'null' },
    { remedi_token: 'mock-1', remedi_user: JSON.stringify({ ...student, role: 'admin' }) },
    { remedi_token: 'mock-1', remedi_user: JSON.stringify({ ...student, id: -1 }) },
    { remedi_token: 'mock-1', remedi_user: JSON.stringify({ ...student, name: ' ' }) }
  ]) {
    const storage = makeStorage({ ...cached, remedi_active_subject: 'math', theme: 'keep' })
    const auth = loadAuth(storage)
    assert.equal(auth.token, '')
    assert.equal(auth.user, null)
    assert.equal(auth.activeSubject, '')
    assert.equal(storage.values.has('remedi_token'), false)
    assert.equal(storage.values.has('remedi_user'), false)
    assert.equal(storage.values.has('remedi_active_subject'), false)
    assert.equal(storage.values.get('theme'), 'keep')
  }
})

test('valid identities restore and stale or invalid subjects are removed', () => {
  const studentStorage = makeStorage({ remedi_token: 'mock-1', remedi_user: JSON.stringify(student), remedi_active_subject: 'math' })
  const studentAuth = loadAuth(studentStorage)
  assert.equal(studentAuth.role, 'student')
  assert.equal(studentAuth.user.student_no, 'S001')
  assert.equal(studentAuth.activeSubject, '')
  assert.equal(studentStorage.values.has('remedi_active_subject'), false)
  const teacherAuth = loadAuth(makeStorage({ remedi_token: 'mock-2', remedi_user: JSON.stringify(teacher), remedi_active_subject: 'math' }))
  assert.equal(teacherAuth.role, 'teacher')
  assert.equal(teacherAuth.activeSubject, 'math')
  const staleSubject = loadAuth(makeStorage({ remedi_token: 'mock-2', remedi_user: JSON.stringify(teacher), remedi_active_subject: 'invalid' }))
  assert.equal(staleSubject.role, 'teacher')
  assert.equal(staleSubject.activeSubject, '')
})

test('blocked browser storage does not prevent in-memory login or logout', () => {
  const auth = loadAuth(makeStorage({}, { read: true, write: true, remove: true }))
  assert.equal(auth.token, '')
  assert.doesNotThrow(() => auth.setSession('mock-1', student))
  assert.equal(auth.role, 'student')
  assert.doesNotThrow(() => auth.logout())
  assert.equal(auth.token, '')
  assert.equal(auth.user, null)
})

test('a partial persistence failure cannot leave mismatched credentials for reload', () => {
  const storage = makeStorage({ theme: 'keep' }, { failWriteAt: 2 })
  const auth = loadAuth(storage)
  auth.setSession('mock-1', student)
  assert.equal(auth.role, 'student')
  assert.equal(storage.values.has('remedi_token'), false)
  assert.equal(storage.values.has('remedi_user'), false)
  assert.equal(storage.values.get('theme'), 'keep')
  const restored = loadAuth(storage)
  assert.equal(restored.token, '')
})

test('student login validates both identity fields before requesting', async () => {
  const { state, requests } = loadLogin(() => { throw new Error('unexpected request') })
  assert.equal(state.username.value, '')
  await state.login()
  assert.equal(state.error.value, '请输入用户名')
  state.username.value = '同学甲'
  await state.login()
  assert.equal(state.error.value, '请输入学号')
  assert.equal(state.loading.value, false)
  assert.equal(requests.length, 0)
})

test('pending login is single-flight, snapshots identity and navigates by returned user', async () => {
  const pending = deferred()
  const { state, requests, sessions, redirects } = loadLogin(() => pending.promise)
  state.username.value = ' 同学甲 '
  state.studentNo.value = ' S001 '
  const login = state.login()
  await state.login()
  state.switchRole('teacher')
  assert.equal(state.role.value, 'student')
  assert.equal(requests.length, 1)
  assert.equal(requests[0].payload.username, '同学甲')
  assert.equal(requests[0].payload.student_no, 'S001')
  assert.equal(requests[0].payload.role, 'student')
  // Even an external state mutation cannot redirect a valid response to the wrong role.
  state.role.value = 'teacher'
  state.username.value = '教师甲'
  pending.resolve({ data: { token: 'mock-1', user: student, active_subject: null } })
  await login
  assert.equal(sessions.length, 1)
  assert.equal(sessions[0][1].role, 'student')
  assert.equal(redirects[0], '/student/chat')
  assert.equal(state.loading.value, false)
})

test('a rejected request releases the form and allows a successful retry', async () => {
  let attempts = 0
  const { state, requests, redirects } = loadLogin(async () => {
    if (++attempts === 1) throw { response: { data: { detail: '姓名与学号不匹配' } } }
    return { data: { token: 'mock-1', user: student, active_subject: null } }
  })
  state.username.value = '同学甲'
  state.studentNo.value = 'S001'
  await state.login()
  assert.equal(state.error.value, '姓名与学号不匹配')
  assert.equal(state.loading.value, false)
  await state.login()
  assert.equal(requests.length, 2)
  assert.equal(redirects[0], '/student/chat')
  assert.equal(state.error.value, '')
})

test('role switches clear the previous identity but selecting the current role preserves input', () => {
  const { state } = loadLogin(() => { throw new Error('unexpected request') })
  state.username.value = '同学甲'
  state.studentNo.value = 'S001'
  state.switchRole('student')
  assert.equal(state.username.value, '同学甲')
  state.switchRole('teacher')
  assert.equal(state.username.value, '')
  assert.equal(state.studentNo.value, '')
})

test('a delayed 401 from the previous account cannot log out the new account', async () => {
  const { api, auth, location } = loadClient('old-token')
  const arrived = deferred(), release = deferred()
  let sentAuthorization
  api.defaults.adapter = async config => {
    sentAuthorization = config.headers.get('Authorization')
    arrived.resolve()
    await release.promise
    return rejectUnauthorized(config)
  }
  const request = api.get('/api/teacher/knowledge/math')
  const rejected = assert.rejects(request, error => error.response?.status === 401)
  await arrived.promise
  auth.token = 'new-token'
  release.resolve()
  await rejected
  assert.equal(sentAuthorization, 'Bearer old-token')
  assert.equal(auth.token, 'new-token')
  assert.equal(auth.logoutCount, 0)
  assert.equal(location.href, 'unchanged')
})

test('a current-account 401 retains the existing logout and redirect behavior', async () => {
  const { api, auth, location } = loadClient('current-token')
  api.defaults.adapter = async config => rejectUnauthorized(config)
  await assert.rejects(api.get('/api/teacher/knowledge/math'), error => error.response?.status === 401)
  assert.equal(auth.token, '')
  assert.equal(auth.logoutCount, 1)
  assert.equal(location.href, '/')
})

test('an anonymous request finishing after login cannot clear the newly established session', async () => {
  const { api, auth, location } = loadClient('')
  const arrived = deferred(), release = deferred()
  api.defaults.adapter = async config => {
    arrived.resolve()
    await release.promise
    return rejectUnauthorized(config)
  }
  const rejected = assert.rejects(api.get('/api/teacher/knowledge/math'), error => error.response?.status === 401)
  await arrived.promise
  auth.token = 'new-token'
  release.resolve()
  await rejected
  assert.equal(auth.token, 'new-token')
  assert.equal(auth.logoutCount, 0)
  assert.equal(location.href, 'unchanged')
})
