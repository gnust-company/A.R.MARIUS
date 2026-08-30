// Bài kiểm đầu tiên của frontend, và nó giữ đúng một lỗi có thật (T142).
//
// `inEvent` trước đây chỉ bật lên ở dòng `event:`. Nên một khối chỉ có `data:` — thứ SSE quy
// định mặc định là `message`, và là thứ `/v1/runs/{id}/stream` **cố ý** gửi để `onmessage` của
// một EventSource thường nghe được hết — được đọc tới hết rồi vứt đi, không một lỗi nào ở đâu
// cả. Không ai phát hiện, vì tới trước màn nhật ký thì chưa màn hình nào nghe một luồng như thế.
//
// Vì sao đáng dựng cả một chỗ chạy bài kiểm cho nó: xoá đúng một dòng `inEvent = true` là mọi
// thứ lại xanh — tsc xanh, eslint xanh, build xanh — và màn nhật ký lặng lẽ im tiếng. Không có
// bài kiểm nào ở đây thì chỗ duy nhất bắt được là một con người mở trình duyệt thật ra xem.

import { afterEach, describe, expect, it, vi } from 'vitest'

import { subscribeSSE, type SSEMessage } from './sse'

/** Một luồng SSE giả, gửi đúng những gì được đưa rồi đóng lại. */
function streamOf(...chunks: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const write = new TextEncoder()
      for (const chunk of chunks) controller.enqueue(write.encode(chunk))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

/** Nghe cho tới khi luồng đóng, rồi ngắt — `subscribeSSE` tự nối lại nếu không ngắt. */
async function heard(): Promise<SSEMessage[]> {
  const got: SSEMessage[] = []
  const stop = subscribeSSE('http://test/stream', (msg) => void got.push(msg))
  await vi.waitFor(() => expect(got.length).toBeGreaterThan(0), { timeout: 1000 })
  stop()
  return got
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('bộ đọc SSE', () => {
  it('đưa được một khối chỉ có data: tới người nghe', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamOf('data: {"seq":1}\n\n')))

    const got = await heard()

    expect(got).toHaveLength(1)
    expect(got[0].data).toBe('{"seq":1}')
  })

  it('gọi tên khối không tên ấy là message, đúng mặc định của SSE', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamOf('data: xin chào\n\n')))

    const got = await heard()

    expect(got[0].type).toBe('message')
  })

  it('vẫn đọc đúng tên khi khối có nói tên mình', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamOf('event: run.event\ndata: {"seq":2}\n\n')))

    const got = await heard()

    expect(got[0].type).toBe('run.event')
    expect(got[0].data).toBe('{"seq":2}')
  })

  it('nối nhiều dòng data: của cùng một khối lại bằng xuống dòng', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamOf('data: dòng một\ndata: dòng hai\n\n')))

    const got = await heard()

    expect(got[0].data).toBe('dòng một\ndòng hai')
  })

  it('không dựng ra một khối rỗng từ dòng trống hay dòng chú thích', async () => {
    // Chú thích `:` là nhịp giữ kết nối mà server gửi khi không có gì để nói. Đọc nó thành
    // một sự kiện là bịa ra một sự kiện mỗi lần đường truyền im lặng.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => streamOf('\n', ': keep-alive\n\n', 'data: thật\n\n')),
    )

    const got = await heard()

    expect(got).toHaveLength(1)
    expect(got[0].data).toBe('thật')
  })

  it('đọc được khối bị cắt làm đôi giữa đường', async () => {
    // Một khối không nhất thiết tới trọn trong một mẩu: TCP cắt ở đâu là chuyện của TCP.
    vi.stubGlobal('fetch', vi.fn(async () => streamOf('data: {"se', 'q":3}\n\n')))

    const got = await heard()

    expect(got[0].data).toBe('{"seq":3}')
  })

  it('nhớ id: của khối để nối lại đúng chỗ đã dừng', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => streamOf('id: 7\ndata: xong\n\n')))

    const got = await heard()

    expect(got[0].id).toBe('7')
  })
})
