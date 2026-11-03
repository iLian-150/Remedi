import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/recognizedMath.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const module = { exports: {} }
vm.runInNewContext(code, { module, exports: module.exports })
const { formatRecognizedMath } = module.exports

assert.equal(formatRecognizedMath('抛物线 y = -x^2 + bx + c'), '抛物线 y = -x² + bx + c')
assert.equal(formatRecognizedMath('(x+1)^{2} + y^3 = 0'), '(x+1)² + y³ = 0')
assert.equal(formatRecognizedMath('x^23 + x^2.5 + x^-2 + x^4'), 'x^23 + x^2.5 + x^-2 + x^4')
assert.equal(formatRecognizedMath('x ^ 2 + (x+1)^{ 3 }'), 'x² + (x+1)³')
assert.equal(formatRecognizedMath('x² + x³'), 'x² + x³')
console.log('识别公式格式检查通过')
