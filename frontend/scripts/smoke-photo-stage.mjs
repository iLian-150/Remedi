// Exercise the real photo component through save failure and retry.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
const require = createRequire(import.meta.url)
const vue = require('vue')
const source = readFileSync(new URL('../src/components/PhotoGradeFlow.vue', import.meta.url), 'utf8')
const compiled = compileScript(parse(source, { filename: 'PhotoGradeFlow.vue' }).descriptor, { id: 'photo-stage-test', inlineTemplate: true })
const code = ts.transpileModule(compiled.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
const module = { exports: {} }
vm.runInNewContext(code, { module, exports: module.exports, URL: { createObjectURL: () => 'blob:fixture' }, console,
  require: (name) => {
    if (name === 'vue') return vue
    if (name === '../stores/student') return { useStudentStore: () => ({}) }
    if (name === '../api/types') return { STEP_STATUS_TEXT: {} }
    if (name === '../utils/errorType') return { sanitizeStudentCopy: (s) => s }
    if (name.endsWith('.vue')) return { default: { render: () => null }, __esModule: true }
    throw new Error(`Unexpected import: ${name}`)
  } })
const node = (type, text = '') => ({ type, text, children: [], parent: null, props: {} })
const renderer = vue.createRenderer({
  createElement: (type) => node(type), createText: (text) => node('#text', text),
  createComment: (text) => node('#comment', text), setText: (n, text) => { n.text = text },
  setElementText: (n, text) => { n.text = text; n.children = [] },
  patchProp: (n, key, _old, value) => { n.props[key] = value },
  insert: (n, parent, anchor) => {
    if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1)
    n.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(n); else parent.children.splice(index, 0, n)
  },
  remove: (n) => { if (n.parent) n.parent.children.splice(n.parent.children.indexOf(n), 1); n.parent = null },
  parentNode: (n) => n.parent, nextSibling: (n) => n.parent?.children[n.parent.children.indexOf(n) + 1] ?? null,
})
const state = vue.reactive({ saving: false, saved: false, error: false })
const received = []
const flow = vue.ref(null)
const root = node('root')
renderer.createApp({ render: () => vue.h(module.exports.default, {
  ref: flow, questionId: 1, direct: true, assignmentAnswer: true,
  assignmentSaving: state.saving, assignmentSaved: state.saved, assignmentError: state.error,
  onAnswered: (file) => { received.push(file); state.error = false; state.saving = true },
}) }).component('router-link', { render: () => null }).mount(root)
const nodes = (n) => [n, ...n.children.flatMap(nodes)]
const text = () => nodes(root).map((n) => n.text).join(' ')
const file = { type: 'image/jpeg', size: 50 }
await flow.value.processFile(file)
await vue.nextTick()
assert.match(text(), /正在保存作答照片/)
assert.doesNotMatch(text(), /作答已添加/)
state.saving = false; state.error = true
await vue.nextTick()
assert.doesNotMatch(text(), /作答已添加/)
const retry = nodes(root).find((n) => n.type === 'button' && n.text === '重试保存')
assert.ok(retry)
retry.props.onClick()
await vue.nextTick()
assert.equal(received.length, 2)
assert.equal(received[1], file)
assert.match(text(), /正在保存作答照片/)
state.saving = false; state.saved = true
await vue.nextTick()
assert.match(text(), /作答已添加/)
console.log('照片保存状态和重试检查通过')
