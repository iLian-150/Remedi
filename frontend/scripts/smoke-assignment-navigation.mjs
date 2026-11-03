// Verify standalone publish routing and legacy workbook links with the real router matcher.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
const require = createRequire(import.meta.url)
const vueRouter = require('vue-router')
const source = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
const module = { exports: {} }
vm.runInNewContext(code, { module, exports: module.exports, require: (name) => {
  if (name === 'vue-router') return { ...vueRouter, createWebHistory: () => vueRouter.createMemoryHistory() }
  if (name === '../stores/auth') return { useAuthStore: () => ({ token: 'fixture', role: 'teacher' }) }
  throw new Error(`Unexpected import: ${name}`)
} })
const router = module.exports.default
for (const mode of ['online', 'offline']) {
  const page = router.resolve({ path: '/teacher/assignments/new', query: { mode, workbook_id: '42' } })
  assert.equal(page.matched.length, 1)
  assert.equal(page.matched[0].path, '/teacher/assignments/new')
  assert.equal(page.matched[0].redirect, undefined)
  assert.equal(page.meta.title, '发布作业')
  assert.equal(page.query.mode, mode)
  assert.equal(page.query.workbook_id, '42')
}
const old = router.resolve('/teacher/assignments?publish=1&mode=offline&workbook_id=42')
const target = old.matched[0].beforeEnter(old)
assert.equal(target.path, '/teacher/assignments/new')
assert.equal(target.query.mode, 'offline')
assert.equal(target.query.workbook_id, '42')
const list = router.resolve('/teacher/assignments?publish=1')
assert.equal(list.matched[0].beforeEnter(list), true)
assert.equal(list.meta.title, '作业管理')
// Mount the real list and cards to verify both choices are immediately visible and navigate.
const vue = require('vue')
const clicked = []
const teacher = { assignmentDateFilter: '', fetchTeacherAssignments: async () => [], setAssignmentDateFilter: () => {} }
const fakeWindow = { addEventListener: () => {}, removeEventListener: () => {}, setInterval: () => 1, clearInterval: () => {}, setTimeout: () => 1 }
function component(path, resolveImport) {
  const text = readFileSync(new URL(path, import.meta.url), 'utf8')
  const descriptor = parse(text, { filename: path }).descriptor
  const script = compileScript(descriptor, { id: path, inlineTemplate: true }).content
  const js = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
  const mod = { exports: {} }
  vm.runInNewContext(js, { module: mod, exports: mod.exports, window: fakeWindow, console,
    require: (name) => { if (name === 'vue') return vue; return resolveImport(name) } })
  return mod.exports.default
}
const icon = { render: () => null }
const cards = component('../src/components/PublishModeCards.vue', (name) => {
  if (name.endsWith('AppIcon.vue')) return { __esModule: true, default: icon }
  throw new Error(`Unexpected import: ${name}`)
})
const listPage = component('../src/views/teacher/TeacherAssignments.vue', (name) => {
  if (name === 'vue-router') return { useRouter: () => ({ push: (target) => clicked.push(target) }) }
  if (name === '../../stores/teacher') return { useTeacherStore: () => teacher }
  if (name === '../../api/client') return { __esModule: true, default: { get: async () => ({ data: [] }) } }
  if (name.endsWith('PublishModeCards.vue')) return { __esModule: true, default: cards }
  if (name.endsWith('.vue')) return { __esModule: true, default: icon }
  throw new Error(`Unexpected import: ${name}`)
})
const makeNode = (type, text = '') => ({ type, text, children: [], parent: null, props: {} })
const renderer = vue.createRenderer({
  createElement: (type) => makeNode(type), createText: (text) => makeNode('#text', text), createComment: (text) => makeNode('#comment', text),
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text; node.children = [] },
  patchProp: (node, key, _old, value) => { node.props[key] = value },
  insert: (node, parent, anchor) => { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = parent; const index = anchor ? parent.children.indexOf(anchor) : -1; if (index < 0) parent.children.push(node); else parent.children.splice(index, 0, node) },
  remove: (node) => { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null },
  parentNode: (node) => node.parent, nextSibling: (node) => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
})
const root = makeNode('root')
const app = renderer.createApp(listPage).component('router-link', { render: () => null })
app.mount(root)
await vue.nextTick()
const nodes = (node) => [node, ...node.children.flatMap(nodes)]
const textOf = (node) => nodes(node).map((item) => item.text).join(' ')
assert.match(textOf(root), /作业管理/)
assert.doesNotMatch(textOf(root), /开始发布/)
for (const [label, mode] of [['线上作业', 'online'], ['线下作业', 'offline']]) {
  const button = nodes(root).find((node) => node.type === 'button' && textOf(node).includes(label))
  assert.ok(button, `${label}入口应直接显示`)
  button.props.onClick()
  const target = clicked.at(-1)
  assert.equal(target.path, '/teacher/assignments/new')
  assert.equal(target.query.mode, mode)
}
app.unmount()

// The standalone form opens the requested mode immediately and keeps a draft when switching modes.
const formRoute = vue.reactive({ query: { mode: 'offline', workbook_id: '42' } })
let leaveGuard
const formTeacher = { fetchWorkbooks: async () => [{ id: 42, title: '练习册' }], fetchClassrooms: async () => [], setAssignmentDateFilter: () => {} }
const formWindow = { ...fakeWindow, confirm: () => false }
const descriptor = parse(readFileSync(new URL('../src/views/teacher/TeacherPublish.vue', import.meta.url), 'utf8'), { filename: 'TeacherPublish.vue' }).descriptor
assert.doesNotMatch(descriptor.template.content, /重新选择发布方式|class="mode-chip"/)
const formScript = compileScript(descriptor, { id: 'publish-form' }).content
const formJs = ts.transpileModule(formScript, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
const formModule = { exports: {} }
vm.runInNewContext(formJs, { module: formModule, exports: formModule.exports, window: formWindow, console, setTimeout, clearTimeout,
  require: (name) => {
    if (name === 'vue') return vue
    if (name === 'vue-router') return { useRoute: () => formRoute, useRouter: () => ({ replace: ({ query }) => { formRoute.query = query; return Promise.resolve() }, push: () => {} }), onBeforeRouteLeave: (guard) => { leaveGuard = guard } }
    if (name === '../../stores/teacher') return { useTeacherStore: () => formTeacher }
    if (name === '../../stores/auth') return { useAuthStore: () => ({ activeSubject: 'math' }) }
    if (name === '../../api/client') return { __esModule: true, default: {} }
    if (name === '../../utils/recognizedMath') return { formatRecognizedMath: (text) => text }
    if (name.endsWith('.vue')) return { __esModule: true, default: icon }
    throw new Error(`Unexpected form import: ${name}`)
  } })
formModule.exports.default.render = () => null
const formRoot = makeNode('root')
const formApp = renderer.createApp(formModule.exports.default)
const formInstance = formApp.mount(formRoot)
const state = formInstance.$.setupState
assert.equal(state.step, 'form')
assert.equal(state.mode, 'offline')
await new Promise((resolve) => setImmediate(resolve))
assert.equal(state.workbookId, 42)
state.title = '未发布草稿'
assert.equal(state.backToChoose, undefined)
state.chooseMode('online')
assert.equal(state.step, 'form')
assert.equal(state.mode, 'online')
assert.equal(state.title, '未发布草稿')
assert.equal(leaveGuard(), false)
state.ok = true
assert.equal(leaveGuard(), undefined)
formApp.unmount()
formRoute.query = { mode: 'offline' }
const chatApp = renderer.createApp(formModule.exports.default, { embedded: true, chatWorkflow: true })
const chatState = chatApp.mount(makeNode('root')).$.setupState
assert.equal(chatState.mode, 'online')
assert.equal(chatState.step, 'form')
await new Promise((resolve) => setImmediate(resolve))
chatApp.unmount()

// Saved grading drafts appear on the assignment list and can be submitted there.
let gradingStatus = 'draft'
let submitCalls = 0
const stagedAssignment = { id: 71, title: '语文作业', description: '', question_count: 4, submitted_count: 0, staged_count: 4, grading_status: 'draft', created_at: '', mode: 'online', workbook_title: null, page_range: null, deadline: null, photo_required: true }
const assignmentStore = {
  assignmentDateFilter: '',
  fetchAssignments: async () => [{ ...stagedAssignment, grading_status: gradingStatus }],
  submitAssignmentForGrading: async () => { submitCalls++; gradingStatus = 'queued'; return { status: 'queued' } },
}
const assignmentDescriptor = parse(readFileSync(new URL('../src/views/student/StudentAssignments.vue', import.meta.url), 'utf8'), { filename: 'StudentAssignments.vue' }).descriptor
const assignmentCode = ts.transpileModule(compileScript(assignmentDescriptor, { id: 'student-progress' }).content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
const assignmentModule = { exports: {} }
vm.runInNewContext(assignmentCode, { module: assignmentModule, exports: assignmentModule.exports, window: fakeWindow, console,
  require: (name) => {
    if (name === 'vue') return vue
    if (name === '../../stores/student') return { useStudentStore: () => assignmentStore }
    if (name.endsWith('AppIcon.vue')) return { __esModule: true, default: icon }
    throw new Error(`Unexpected student assignment import: ${name}`)
  } })
assignmentModule.exports.default.render = () => null
const assignmentListApp = renderer.createApp(assignmentModule.exports.default)
const assignmentListState = assignmentListApp.mount(makeNode('root')).$.setupState
await new Promise((resolve) => setImmediate(resolve))
assert.equal(assignmentListState.doneCount(stagedAssignment), 4)
assert.equal(assignmentListState.stampOf(stagedAssignment).text, '待提交')
assert.equal(assignmentListState.canSubmitStagedAssignment(stagedAssignment), true)
await assignmentListState.submitStagedAssignment(stagedAssignment)
assert.equal(submitCalls, 1)
assert.equal(assignmentListState.stampOf({ ...stagedAssignment, grading_status: gradingStatus }).text, '批改中')
assignmentListApp.unmount()
console.log('作业发布入口和旧链接检查通过')
