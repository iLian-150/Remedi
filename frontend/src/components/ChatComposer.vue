<template>
  <div class="chat-composer" :class="{ 'chat-composer-welcome': welcome }">
    <div class="chat-inner">
      <div class="composer-panel">
        <div v-if="selectedImage && selectedImageUrl" class="composer-image-preview">
          <button
            class="composer-image-open"
            type="button"
            aria-label="放大待发送图片"
            @click="emit('preview-image', selectedImageUrl, selectedImage.name || '待发送图片')"
          >
            <img :src="selectedImageUrl" :alt="selectedImage.name || '待发送图片'" />
          </button>
          <button
            class="composer-image-remove"
            type="button"
            aria-label="移除图片"
            title="移除图片"
            :disabled="sending"
            @click="emit('clear-image')"
          >
            <AppIcon name="x" :size="15" />
          </button>
        </div>
        <textarea
          :value="modelValue"
          class="chat-text-input"
          rows="1"
          aria-label="输入内容"
          placeholder="输入内容…"
          :disabled="sending"
          @input="onInput"
          @keydown.enter.exact.prevent="emit('send')"
        ></textarea>
        <div class="composer-bottom-row">
          <input
            ref="fileRef"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            @change="onFileChange"
          />
          <div class="composer-tools">
            <button
              class="composer-photo-btn"
              type="button"
              aria-label="上传题目图片"
              title="上传题目图片"
              :disabled="photoDisabled"
              @click="fileRef?.click()"
            >
              <AppIcon name="camera" :size="18" />
            </button>
            <span v-if="contextText" class="composer-context">
              <AppIcon name="clipboard" :size="13" /> {{ contextText }}
            </span>
          </div>
          <button
            class="btn send-btn"
            type="button"
            :aria-label="selectedImage ? '发送图片' : '发送'"
            :title="selectedImage ? '发送图片' : '发送'"
            :disabled="sending || (!modelValue.trim() && !selectedImage)"
            @click="emit('send')"
          >
            <AppIcon name="send" :size="17" />
          </button>
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
  selectedImage: File | null
  selectedImageUrl: string
  sending: boolean
  photoDisabled: boolean
  contextText?: string
  welcome?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  'image-selected': [file: File]
  'clear-image': []
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
  if (file) emit('image-selected', file)
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
@media (prefers-reduced-motion: reduce) {
  .composer-panel, .send-btn, .composer-photo-btn { transition: none; animation: none; }
  .send-btn:hover:not(:disabled) { transform: none; }
}
@media (max-width: 960px) {
  .chat-inner { padding-right: 14px; padding-left: 14px; }
  .composer-panel { padding: 10px 11px; }
}
@media (max-width: 620px) {
  .composer-bottom-row { gap: 6px; }
  .composer-tools { gap: 5px; }
  .composer-context { max-width: 38vw; }
}
</style>
