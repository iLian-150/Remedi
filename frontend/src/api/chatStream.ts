// 主聊天和错题本复用 SSE 读取与逐字显示；调用方分别指定独立的接口和请求体。
import api from './client'
import { useAuthStore } from '../stores/auth'

// Keep updates slower than a 60 Hz paint interval so each streamed character
// can appear in its own rendered frame instead of being visually batched.
const TYPEWRITER_INTERVAL_MS = 18

function waitForNextCharacter(): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, TYPEWRITER_INTERVAL_MS))
}

function throwIfAborted(signal?: AbortSignal): void {
  if (!signal?.aborted) return
  const error = new Error('请求已取消')
  error.name = 'AbortError'
  throw error
}

export async function streamChatReply<T extends { reply: string }>(
  path: string,
  payload: object,
  onText: (text: string) => void,
  signal?: AbortSignal
): Promise<T> {
  const auth = useAuthStore()
  const requestToken = auth.token
  const response = await fetch(api.getUri({ url: path }), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(requestToken ? { Authorization: `Bearer ${requestToken}` } : {})
    },
    body: JSON.stringify(payload),
    signal
  })

  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: unknown } | null
    if (response.status === 401 && auth.token === requestToken) {
      auth.logout()
      if (window.location.pathname !== '/') window.location.href = '/'
    }
    const detail = typeof payload?.detail === 'string' ? payload.detail : ''
    throw new Error(detail || `学习助手请求失败（HTTP ${response.status}）`)
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('浏览器无法读取学习助手的流式回复。')
  const decoder = new TextDecoder()
  let buffer = ''
  let result: T | null = null
  let finalReply = ''
  const characterQueue: string[] = []
  let queueOffset = 0
  let typingTask: Promise<void> | null = null
  let streamedText = ''

  const startTypewriter = () => {
    if (signal?.aborted) {
      characterQueue.length = 0
      queueOffset = 0
      return
    }
    if (typingTask || queueOffset >= characterQueue.length) return
    typingTask = (async () => {
      while (queueOffset < characterQueue.length && !signal?.aborted) {
        onText(characterQueue[queueOffset++])
        await waitForNextCharacter()
      }
    })().finally(() => {
      typingTask = null
      characterQueue.splice(0, queueOffset)
      queueOffset = 0
      if (characterQueue.length) startTypewriter()
    })
  }

  const waitForTypewriter = async () => {
    while (typingTask) await typingTask
    if (characterQueue.length) {
      startTypewriter()
      await waitForTypewriter()
    }
  }

  const consumeEvent = (block: string) => {
    let eventName = ''
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue
      const separator = line.indexOf(':')
      const field = separator < 0 ? line : line.slice(0, separator)
      let value = separator < 0 ? '' : line.slice(separator + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') eventName = value
      else if (field === 'data') dataLines.push(value)
    }
    if (!dataLines.length) return
    const payload = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
    if (eventName === 'token') {
      const text = typeof payload.text === 'string' ? payload.text : ''
      if (text) {
        streamedText += text
        // 网络流持续读取；独立的队列逐字渲染，避免打字延时反压模型流。
        characterQueue.push(...Array.from(text))
        startTypewriter()
      }
    } else if (eventName === 'done') {
      result = payload as unknown as T
      finalReply = typeof payload.reply === 'string' ? payload.reply : ''
    } else if (eventName === 'error') {
      throw new Error(typeof payload.detail === 'string' ? payload.detail : '回复生成中断，请稍后重试。')
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        consumeEvent(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
    if (buffer.trim()) consumeEvent(buffer)
  } catch (error) {
    await waitForTypewriter()
    throw error
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
  if (finalReply.startsWith(streamedText) && finalReply.length > streamedText.length) {
    characterQueue.push(...Array.from(finalReply.slice(streamedText.length)))
    startTypewriter()
  }
  await waitForTypewriter()
  throwIfAborted(signal)
  if (!result) throw new Error('学习助手的流式回复没有正常结束，请重试。')
  return result
}
