// Exercise the real student answer component with a private image draft and explicit submission.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'

const require = createRequire(import.meta.url)
const vue = require('vue')
const descriptor = parse(readFileSync(new URL('../src/views/student/StudentSubmit.vue', import.meta.url), 'utf8'), { filename: 'StudentSubmit.vue' }).descriptor
const script = compileScript(descriptor, { id: 'student-submit' }).content
const code = ts.transpileModule(script, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
const module = { exports: {} }
const answered = new Set()
const images = new Set()
let submissions = 0
let imageReads = 0
let failSave = false
const status = (value = 'draft') => ({ status: value, progress: 0, total_questions: 2, answered_question_ids: [...answered], image_question_ids: [...images] })
const student = {
  fetchAssignments: async () => [{ id: 1, title: '作业', question_count: 2, submitted_count: 0, photo_required: false }],
  fetchLatestQuestionSubmissionStatuses: async () => [],
  fetchAssignmentDetail: async () => ({ id: 1, mode: 'online', groups: [], questions: [{ id: 11, subject: 'chinese', stem: '第一题' }, { id: 12, subject: 'chinese', stem: '第二题' }] }),
  fetchAssignmentGradingStatus: async () => status(),
  stageAssignmentAnswer: async (_id, qid, payload) => {
    if (failSave) throw new Error('save failed')
    answered.add(qid)
    if (payload.file) images.add(qid); else images.delete(qid)
    return status()
  },
  fetchStagedAnswerImage: async () => { imageReads++; return new Blob(['saved']) },
  submitAssignmentForGrading: async () => { submissions++; return status('queued') },
}
let nextUrl = 0
const revoked = []
const fakeURL = { createObjectURL: () => `blob:test-${++nextUrl}`, revokeObjectURL: (url) => revoked.push(url) }
const fakeWindow = { setInterval: () => 1, clearInterval: () => {}, setTimeout: () => 1 }
const fakeDocument = { addEventListener: () => {}, removeEventListener: () => {} }
const fakeStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
vm.runInNewContext(code, { module, exports: module.exports, window: fakeWindow, document: fakeDocument, localStorage: fakeStorage, URL: fakeURL, console: { error: () => {} },
  require: (name) => {
    if (name === 'vue') return vue
    if (name === 'vue-router') return { useRoute: () => ({ query: { assignment_id: '1' } }), useRouter: () => ({ replace: () => {} }) }
    if (name === '../../stores/student') return { useStudentStore: () => student }
    if (name.endsWith('.vue')) return { __esModule: true, default: { render: () => null } }
    throw new Error(`Unexpected import: ${name}`)
  } })
module.exports.default.render = () => null
const makeNode = (type) => ({ type, children: [], parent: null })
const renderer = vue.createRenderer({
  createElement: makeNode, createText: makeNode, createComment: makeNode,
  setText: () => {}, setElementText: () => {}, patchProp: () => {},
  insert: (node, parent) => { node.parent = parent; parent.children.push(node) },
  remove: () => {}, parentNode: (node) => node.parent, nextSibling: () => null,
})
const flush = async () => { await new Promise((resolve) => setImmediate(resolve)); await vue.nextTick() }
function mount() {
  const app = renderer.createApp(module.exports.default)
  const instance = app.mount(makeNode('root'))
  return { app, state: instance.$.setupState }
}
const file = { type: 'image/jpeg', size: 100 }
const first = mount()
await flush()
assert.equal(first.state.questions.length, 2)
assert.equal(first.state.currentQ.subject, 'chinese', '线上非数学题也应使用可输入和电子手写作答板')
await first.state.selectOnlinePhoto(11, file)
assert.match(first.state.photoPreviews[11], /^blob:/)
assert.equal(first.state.answeredCount, 1)
assert.equal(first.state.canSubmitAssignment, false)
failSave = true
await first.state.selectOnlinePhoto(12, file)
assert.match(first.state.photoPreviews[12], /^blob:/)
assert.equal(first.state.canSubmitAssignment, false)
failSave = false
await first.state.saveStagedAnswer(12, { file })
assert.equal(first.state.canSubmitAssignment, true)
assert.equal(submissions, 0, '保存最后一道题不能自动提交')
first.app.unmount()
assert.ok(revoked.length >= 2)

const refreshed = mount()
await flush()
await flush()
assert.equal(refreshed.state.canSubmitAssignment, true)
assert.equal(submissions, 0, '刷新不能自动提交')
assert.ok(imageReads > 0, '刷新后应重新读取已保存的图片')
assert.match(refreshed.state.photoPreviews[11], /^blob:/)
await refreshed.state.queueWholeAssignment()
assert.equal(submissions, 1)
assert.equal(refreshed.state.gradingJobStatus, 'queued')
refreshed.state.applyGradingStatus({ ...status('failed'), error: '第 2 题的作答未能识别，请检查后重新提交。' })
assert.equal(refreshed.state.gradingJobError, '第 2 题的作答未能识别，请检查后重新提交。')
refreshed.app.unmount()
console.log('Student image preview and explicit assignment submission: OK')
