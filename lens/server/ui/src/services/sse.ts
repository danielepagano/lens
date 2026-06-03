/**
 * Parse SSE (Server-Sent Events) from a fetch response body.
 * Used by CLI run stream and later by operator streams.
 */

export interface ParsedSSEEvent {
  data: string
}

/**
 * Consume a ReadableStream and yield parsed SSE events (one per "data: ..." block).
 * Lines are decoded as UTF-8; events are delimited by double newline.
 */
export async function* parseSSEFromStream(
  stream: ReadableStream<Uint8Array>
): AsyncGenerator<ParsedSSEEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() ?? ''
      for (const block of parts) {
        const line = block.split('\n').find((l) => l.startsWith('data: '))
        if (line !== undefined) {
          yield { data: line.slice(6).trim() }
        }
      }
    }
    if (buffer.trim()) {
      const line = buffer.split('\n').find((l) => l.startsWith('data: '))
      if (line !== undefined) {
        yield { data: line.slice(6).trim() }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
