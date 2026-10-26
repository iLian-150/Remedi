<template>
  <aside v-if="visible" class="app-update-notice" role="status" aria-live="polite">
    <AppIcon name="refresh" :size="16" />
    <span>应用已更新</span>
    <button class="btn small" type="button" @click="reload">刷新</button>
    <button class="icon-btn" type="button" aria-label="关闭更新提示" @click="dismiss">
      <AppIcon name="x" :size="16" />
    </button>
  </aside>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from './icons/AppIcon.vue'

const currentAssets = getAssetSignature(document)
const availableAssets = ref('')
const dismissedAssets = ref('')
const visible = computed(() => Boolean(availableAssets.value && availableAssets.value !== dismissedAssets.value))
let pollId: number | undefined
let checking = false

function getAssetSignature(doc: Document): string {
  const scripts = Array.from(doc.querySelectorAll<HTMLScriptElement>('script[type="module"][src]'))
    .map((script) => script.getAttribute('src'))
  const stylesheets = Array.from(doc.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"][href]'))
    .map((link) => link.getAttribute('href'))
  return [...scripts, ...stylesheets].filter((asset): asset is string => Boolean(asset)).sort().join('\n')
}

async function checkForUpdate() {
  if (import.meta.env.DEV || document.hidden || checking || !currentAssets) return
  checking = true

  try {
    const response = await fetch('/index.html', { cache: 'no-store' })
    if (!response.ok) return

    const html = await response.text()
    const latestAssets = getAssetSignature(new DOMParser().parseFromString(html, 'text/html'))

    if (latestAssets && latestAssets !== currentAssets) {
      availableAssets.value = latestAssets
    } else {
      availableAssets.value = ''
      dismissedAssets.value = ''
    }
  } catch {
    // 更新检查失败不影响当前页面操作。
  } finally {
    checking = false
  }
}

function onVisibilityChange() {
  if (!document.hidden) void checkForUpdate()
}

function dismiss() {
  dismissedAssets.value = availableAssets.value
}

function reload() {
  window.location.reload()
}

onMounted(() => {
  void checkForUpdate()
  pollId = window.setInterval(() => void checkForUpdate(), 60_000)
  window.addEventListener('focus', checkForUpdate)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  if (pollId !== undefined) window.clearInterval(pollId)
  window.removeEventListener('focus', checkForUpdate)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.app-update-notice {
  position: fixed;
  z-index: 600;
  top: 14px;
  left: 50%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px 8px 13px;
  transform: translateX(-50%);
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--card);
  box-shadow: var(--shadow-md);
  color: var(--text-2);
  font-size: 13px;
  white-space: nowrap;
}

.app-update-notice > svg { color: var(--primary); }
.app-update-notice .btn { padding: 5px 12px; border-radius: 999px; }
.app-update-notice .icon-btn { width: 28px; height: 28px; }

@media (max-width: 480px) {
  .app-update-notice { top: 10px; max-width: calc(100vw - 20px); gap: 7px; font-size: 12px; }
}
</style>
