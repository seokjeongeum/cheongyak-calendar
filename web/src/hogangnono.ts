import type { Notice } from './types'

/** The server resolves and verifies the complex when collecting the notice. */
export function hogangnonoDetailUrl(notice: Partial<Pick<Notice, 'hogangnono_url'>>): string | undefined {
  if (!notice.hogangnono_url) return undefined
  try {
    const url = new URL(notice.hogangnono_url)
    if (url.protocol !== 'https:' || url.hostname !== 'hogangnono.com'
      || url.username || url.password || url.port || url.search || url.hash
      || !/^\/apt\/[a-zA-Z0-9]+$/u.test(url.pathname)) return undefined
    return url.href
  } catch { return undefined }
}
