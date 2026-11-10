<template>
  <div class="chat-composer" :class="{ 'chat-composer-welcome': welcome, 'chat-composer-single-line': singleLine }">
    <div class="chat-inner">
      <div class="composer-panel" :class="{ 'composer-panel-single-line': singleLine, 'composer-panel-has-file': singleLine && !!selectedFile }">
        <div v-if="selectedFile && selectedFile.type.startsWith('image/') && selectedFileUrl" class="composer-image-preview">
          <button
            class="composer-image-open"
            type="button"
            aria-label="放大待发送图片"
            @click="emit('preview-image', selectedFileUrl, selectedFile.name || '待发送图片')"
          >
            <img :src="selectedFileUrl" :alt="selectedFile.name || '待发送图片'" />
          </button>
          <button
            class="composer-image-remove"
            type="button"
            aria-label="移除图片"
            title="移除图片"
            :disabled="sending || uploadDisabled"
            @click="emit('clear-file')"
          >
            <AppIcon name="x" :size="15" />
          </button>
        </div>
        <div v-else-if="selectedFile" class="composer-file-preview">
          <AppIcon name="file" :size="18" />
          <span class="composer-file-name" :title="selectedFile.name">{{ selectedFile.name }}</span>
          <span class="composer-file-size">{{ formatFileSize(selectedFile.size) }}</span>
          <button
            class="composer-file-remove"
            type="button"
            aria-label="移除文件"
            title="移除文件"
            :disabled="sending || uploadDisabled"
            @click="emit('clear-file')"
          >
            <AppIcon name="x" :size="15" />
          </button>
        </div>
        <div class="composer-entry">
          <textarea
            :value="modelValue"
            class="chat-text-input"
            rows="1"
            aria-label="输入内容"
            :placeholder="singleLine ? '说说你想了解什么…' : '输入内容…'"
            :disabled="sending"
            @input="onInput"
            @keydown.enter.exact.prevent="emit('send')"
          ></textarea>
          <div class="composer-bottom-row">
            <input
              ref="fileRef"
              type="file"
              accept=".pdf,.docx,.pptx,.xlsx,.xlsm,.txt,.md,.csv,.tsv,.html,.htm,.json,.xml,.yaml,.yml,image/jpeg,image/png,image/webp"
              hidden
              @change="onFileChange"
            />
            <div class="composer-tools">
              <button
                class="composer-photo-btn"
                type="button"
                aria-label="上传文件"
                title="上传文件"
                :disabled="uploadDisabled"
                @click="fileRef?.click()"
              >
                <AppIcon name="file" :size="18" />
              </button>
              <span v-if="contextText" class="composer-context">
                <AppIcon name="clipboard" :size="13" /> {{ contextText }}
              </span>
            </div>
            <button
              class="btn send-btn"
              type="button"
              :aria-label="selectedFile ? '发送文件' : '发送'"
              :title="selectedFile ? '发送文件' : '发送'"
              :disabled="sending || (!modelValue.trim() && !selectedFile)"
              @click="emit('send')"
            >
              <AppIcon name="send" :size="17" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from './icons/AppIcon.vue'

defineProps<{
  modelValue: string
  selectedFile: File | null
  selectedFileUrl: string
  sending: boolean
  uploadDisabled: boolean
  contextText?: string
  welcome?: boolean
  singleLine?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  'file-selected': [file: File]
  'clear-file': []
  'preview-image': [url: string, alt: string]
}>()

const fileRef = ref<HTMLInputElement | null>(null)

function onInput(event: Event) {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

function onFileChange(event: Event) {
  const picker = event.target as HTMLInputElement
  const file = picker.files?.[0]
  picker.value = ''
  if (file) emit('file-selected', file)
}

function formatFileSize(size: number): string {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`
}
</script>

<style scoped>
.chat-inner { max-width: 1280px; width: 100%; margin: 0 auto; padding: 0 20px; }
.chat-composer { position: absolute; left: 0; right: 0; bottom: 0; z-index: 6; background: transparent; padding: 10px 0 14px; }
.chat-composer-welcome { background: transparent; }
.composer-panel {
  display: flex; flex-direction: column;
  border: 1px solid rgba(211, 221, 235, 0.95); border-radius: 20px;
  background: rgba(255, 255, 255, 0.94);
  -webkit-backdrop-filter: blur(14px) saturate(1.4);
  backdrop-filter: blur(14px) saturate(1.4);
  padding: 13px 15px 11px;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.11), 0 2px 8px rgba(15, 23, 42, 0.045);
  transition: border-color 0.18s ease, box-shadow 0.25s ease;
}
.composer-entry { display: flex; min-width: 0; flex-direction: column; }
.composer-panel:focus-within {
  border-color: rgba(29, 78, 216, 0.35);
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 2px 8px rgba(15, 23, 42, 0.06), 0 0 0 3px rgba(29, 78, 216, 0.14);
}
.composer-image-preview { position: relative; width: fit-content; max-width: min(132px, 100%); margin: 0 8px 8px; }
.composer-image-open { display: block; max-width: 100%; max-height: 92px; padding: 3px; overflow: hidden; border: 1px solid var(--border); border-radius: 11px; background: #fff; cursor: zoom-in; }
.composer-image-open img { display: block; width: auto; height: auto; max-width: 122px; max-height: 84px; object-fit: contain; border-radius: 8px; }
.composer-image-remove { position: absolute; top: 8px; right: 8px; display: inline-flex; width: 28px; height: 28px; align-items: center; justify-content: center; border: 1px solid var(--border); border-radius: 50%; background: rgba(255, 255, 255, 0.96); color: var(--text-2); box-shadow: 0 2px 8px rgba(15, 23, 42, 0.16); cursor: pointer; }
.composer-image-remove:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
.composer-image-remove:disabled { opacity: 0.55; cursor: not-allowed; }
.composer-file-preview { display: flex; min-width: 0; align-items: center; gap: 9px; margin: 0 8px 8px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 12px; background: var(--gray-bg); color: var(--text-2); }
.composer-file-name { overflow: hidden; color: var(--text-1); font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.composer-file-size { flex-shrink: 0; color: var(--text-3); font-size: 11px; }
.composer-file-remove { display: inline-flex; width: 26px; height: 26px; flex-shrink: 0; align-items: center; justify-content: center; margin-left: auto; border: 1px solid var(--border); border-radius: 50%; background: #fff; color: var(--text-2); cursor: pointer; }
.composer-file-remove:hover:not(:disabled) { border-color: var(--red); color: var(--red); }
.composer-file-remove:disabled { opacity: 0.55; cursor: not-allowed; }
.chat-text-input { display: block; width: 100%; min-width: 0; min-height: 40px; max-height: 150px; resize: none; padding: 7px 8px; border: 0; border-radius: 10px; outline: 0; box-shadow: none; font: inherit; font-size: 15px; line-height: 1.65; }
.chat-text-input:focus { border: 0; outline: 0; box-shadow: none; }
.composer-bottom-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 7px; }
.composer-tools { display: flex; min-width: 0; align-items: center; gap: 9px; }
.composer-photo-btn { display: inline-flex; width: 42px; height: 42px; align-items: center; justify-content: center; border: 1px solid var(--border); border-radius: 50%; background: #fff; color: var(--text-2); padding: 0; cursor: pointer; transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease, transform 0.2s ease; }
.composer-photo-btn:hover:not(:disabled) { border-color: rgba(29, 78, 216, 0.35); background: var(--primary-50); color: var(--primary); }
.composer-photo-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.composer-context { display: inline-flex; min-width: 0; align-items: center; gap: 5px; overflow: hidden; color: var(--text-3); font-size: 11.5px; white-space: nowrap; text-overflow: ellipsis; }
.send-btn { display: inline-flex; width: 42px; height: 42px; align-items: center; justify-content: center; padding: 0; border-radius: 50%; flex-shrink: 0; transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease; }
.send-btn:hover:not(:disabled) { transform: scale(1.07); }
.send-btn:disabled { background: var(--gray-bg); color: var(--text-3); cursor: default; }
.send-btn:not(:disabled) { box-shadow: 0 3px 9px rgba(29, 78, 216, 0.2); }
.chat-composer .chat-inner { max-width: 860px; }
.chat-composer-single-line .chat-inner { max-width: 1100px; }
.composer-panel-single-line {
  align-items: center;
  flex-direction: row;
  padding: 6px 8px 6px 22px;
  border-radius: var(--radius-pill);
  background: var(--surface-2);
  box-shadow: none;
}
.composer-panel-single-line:focus-within {
  border-color: color-mix(in srgb, var(--primary) 32%, var(--border));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 12%, transparent);
}
.composer-panel-single-line .composer-entry { width: 100%; flex-direction: row; align-items: center; gap: 8px; }
.composer-panel-single-line .chat-text-input {
  flex: 1;
  width: auto;
  min-height: 48px;
  max-height: 48px;
  padding: 0 4px;
  background: transparent;
  font-size: 16px;
}
.composer-panel-single-line .composer-bottom-row { flex-shrink: 0; margin-top: 0; gap: 4px; }
.composer-panel-single-line .composer-tools { gap: 0; }
.composer-panel-single-line .composer-photo-btn { width: 38px; height: 38px; border-color: transparent; background: transparent; }
.composer-panel-single-line .composer-photo-btn:hover:not(:disabled) { background: var(--primary-50); }
.composer-panel-single-line .send-btn { width: 42px; height: 42px; }
.composer-panel-single-line.composer-panel-has-file { align-items: stretch; flex-direction: column; }
.composer-panel-single-line.composer-panel-has-file .composer-entry { width: 100%; }
@media (prefers-reduced-motion: reduce) {
  .composer-panel, .send-btn, .composer-photo-btn { transition: none; animation: none; }
  .send-btn:hover:not(:disabled) { transform: none; }
}
@media (max-width: 960px) {
  .chat-inner { padding-right: 14px; padding-left: 14px; }
  .composer-panel { padding: 10px 11px; }
  .composer-panel-single-line { padding: 6px 7px 6px 16px; }
}
@media (max-width: 620px) {
  .composer-bottom-row { gap: 6px; }
  .composer-tools { gap: 5px; }
  .composer-context { max-width: 38vw; }
  .composer-panel-single-line { padding-left: 13px; }
  .composer-panel-single-line .composer-entry { gap: 4px; }
  .composer-panel-single-line .composer-photo-btn { width: 34px; height: 34px; }
  .composer-panel-single-line .send-btn { width: 38px; height: 38px; }
}
</style>
