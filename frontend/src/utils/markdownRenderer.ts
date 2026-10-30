import MarkdownIt from 'markdown-it'

/** Create a message-aware Markdown renderer that skips unchanged message text. */
export function createMarkdownRenderer<T extends object>(
  getText: (message: T) => string
) {
  const markdown = new MarkdownIt({
    html: false,
    // Keep model line breaks as Markdown soft breaks instead of forcing <br>.
    breaks: false,
    linkify: false,
    typographer: false
  })
  const renderedByMessage = new WeakMap<T, { source: string; html: string }>()

  return (message: T, text = getText(message)): string => {
    const source = text || ''
    const cached = renderedByMessage.get(message)
    if (cached?.source === source) return cached.html

    const formulas: Array<{ token: string; display: boolean; text: string }> = []
    const withMathTokens = source
      .replace(/\\\[([\s\S]*?)\\\]/g, (_match, formula: string) => addMathToken(formulas, formula, true))
      .replace(/\$\$([\s\S]*?)\$\$/g, (_match, formula: string) => addMathToken(formulas, formula, true))
      .replace(/\\\(([\s\S]*?)\\\)/g, (_match, formula: string) => addMathToken(formulas, formula, false))
    const normalized = withMathTokens
      .replace(/\r\n?/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
    let html = markdown.render(normalized)
    for (const formula of formulas) {
      const rendered = escapeHtml(formatLatexAsText(formula.text))
      if (formula.display) {
        html = html.split(`<p>${formula.token}</p>`).join(`<div class="markdown-math-display">${rendered}</div>`)
      } else {
        html = html.split(formula.token).join(`<span class="markdown-math-inline">${rendered}</span>`)
      }
    }
    renderedByMessage.set(message, { source, html })
    return html
  }
}

function addMathToken(
  formulas: Array<{ token: string; display: boolean; text: string }>,
  text: string,
  display: boolean
): string {
  const token = `REMEDIMATH${formulas.length}TOKEN`
  formulas.push({ token, display, text })
  return display ? `\n\n${token}\n\n` : token
}

/** Keep common LaTeX from leaking into chat when older answers contain formulas. */
function formatLatexAsText(value: string): string {
  return value
    .replace(/\\(?:text|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}/g, '$1')
    .replace(/\\(?:left|right|displaystyle)\b/g, '')
    .replace(/\\boxed\s*\{([^{}]*)\}/g, '$1')
    .replace(/\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, '$1/$2')
    .replace(/\\sqrt\s*\{([^{}]*)\}/g, '√($1)')
    .replace(/\\times\b/g, '×')
    .replace(/\\cdot\b/g, '·')
    .replace(/\\div\b/g, '÷')
    .replace(/\\(?:leq|le)\b/g, '≤')
    .replace(/\\(?:geq|ge)\b/g, '≥')
    .replace(/\\neq\b/g, '≠')
    .replace(/\\approx\b/g, '≈')
    .replace(/\\pi\b/g, 'π')
    .replace(/\\theta\b/g, 'θ')
    .replace(/\\alpha\b/g, 'α')
    .replace(/\\beta\b/g, 'β')
    .replace(/\\quad\b|\\,|\\;/g, ' ')
    .replace(/\^\{([0-9+-]+)\}/g, (_match, exponent: string) => toSuperscript(exponent))
    .replace(/_\{([0-9+-]+)\}/g, (_match, subscript: string) => toSubscript(subscript))
    .replace(/[{}]/g, '')
    .replace(/\\/g, '')
    .replace(/[ \t]+/g, ' ')
    .trim()
}

function toSuperscript(value: string): string {
  const chars: Record<string, string> = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '+': '⁺', '-': '⁻' }
  return [...value].map((char) => chars[char] || char).join('')
}

function toSubscript(value: string): string {
  const chars: Record<string, string> = { '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉', '+': '₊', '-': '₋' }
  return [...value].map((char) => chars[char] || char).join('')
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char] || char)
}
