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

    const normalized = source
      .replace(/\r\n?/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
    const html = markdown.render(normalized)
    renderedByMessage.set(message, { source, html })
    return html
  }
}
