import { nextTick, onBeforeUnmount, ref, type Ref } from 'vue'

interface ThreadScrollState {
  scrollTop: number
  followingLatest: boolean
}

const FOLLOW_DISTANCE_PX = 120

export function useChatThreadViewport(sessionId: Ref<string>) {
  const threadElement = ref<HTMLElement | null>(null)
  const followingLatest = ref(true)
  const latestAvailable = ref(false)
  const scrollStates = new Map<string, ThreadScrollState>()
  let scrollFrame: number | null = null

  function nearBottom(element: HTMLElement): boolean {
    return element.scrollHeight - element.scrollTop - element.clientHeight <= FOLLOW_DISTANCE_PX
  }

  function rememberThreadPosition(key = sessionId.value) {
    const element = threadElement.value
    if (!element || !key) return
    scrollStates.set(key, {
      scrollTop: element.scrollTop,
      followingLatest: followingLatest.value,
    })
  }

  function updateScrollState() {
    scrollFrame = null
    const element = threadElement.value
    if (!element) return
    followingLatest.value = nearBottom(element)
    if (followingLatest.value) latestAvailable.value = false
    rememberThreadPosition()
  }

  function handleThreadScroll() {
    if (scrollFrame !== null) return
    if (typeof window.requestAnimationFrame === 'function') {
      scrollFrame = window.requestAnimationFrame(updateScrollState)
    } else {
      updateScrollState()
    }
  }

  async function jumpToLatest() {
    await nextTick()
    const element = threadElement.value
    if (!element) return
    element.scrollTop = element.scrollHeight
    followingLatest.value = true
    latestAvailable.value = false
    rememberThreadPosition()
  }

  async function restoreSessionPosition() {
    await nextTick()
    const element = threadElement.value
    if (!element) return
    const state = scrollStates.get(sessionId.value)
    if (!state) {
      await jumpToLatest()
      return
    }
    element.scrollTop = Math.min(state.scrollTop, Math.max(0, element.scrollHeight - element.clientHeight))
    followingLatest.value = state.followingLatest && nearBottom(element)
    latestAvailable.value = false
  }

  async function contentChanged(forceFollow = false) {
    await nextTick()
    if (forceFollow || followingLatest.value) {
      await jumpToLatest()
      return
    }
    latestAvailable.value = true
    rememberThreadPosition()
  }

  onBeforeUnmount(() => {
    if (scrollFrame !== null && typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(scrollFrame)
    }
  })

  return {
    threadElement,
    followingLatest,
    latestAvailable,
    rememberThreadPosition,
    handleThreadScroll,
    jumpToLatest,
    restoreSessionPosition,
    contentChanged,
  }
}
