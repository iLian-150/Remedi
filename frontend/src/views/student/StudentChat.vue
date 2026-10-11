<!-- 学生端学习助手首页：新对话显示欢迎页和学习进度；开始对话后切换到消息流。
     保留 Remedi 蓝色视觉、作业拍照批改、文字问答和错题本收录。
     v0.8.1 合并修复：会话改走 store 状态层（watch sessionView 同步），
     输入区恢复 v0.6.2 的悬浮毛玻璃卡（原弹层式历史面板与页面自持会话状态已移除）。
     v0.8.2：页内侧栏整套删除——导航与会话区统一由 App.vue 全局侧栏承载
     （全局侧栏在对话页挂 SidebarSessions），本页回归普通内容布局。 -->
<template>
  <div class="chat-layout">
    <!-- 顶部：智能批改标题（会话操作在左侧栏会话区，v0.8.1） -->
    <div class="chat-header">
      <div class="chat-inner">
        <div class="chat-title">
          <span class="chat-title-mark"><AppIcon name="sparkles" :size="17" /></span>
          <span class="chat-title-copy">
            <strong>Remedi 学习助手</strong>
            <small>作业批改 · 错题复习 · 学习问答</small>
          </span>
          <span class="chat-status"><i></i> 随时可以提问</span>
        </div>
      </div>
    </div>

    <div class="chat-content-shell" :class="{ 'welcome-mode': isWelcomeScreen }">
    <!-- 消息流 / AI 首页 -->
    <div class="chat-body" :class="{ 'chat-body-welcome': isWelcomeScreen }" ref="bodyRef">
      <div class="chat-inner">
        <section v-if="isWelcomeScreen" class="welcome-home">
          <div class="welcome-kicker">今日学习</div>
          <h1>{{ auth.name || '同学' }}，今天想聊点什么？</h1>
          <p class="welcome-description">学习中遇到的问题、作业批改或错题复习，都可以在这里聊。</p>

          <div v-if="welcomeBriefing" class="welcome-briefing">
            <div class="welcome-briefing-heading">
              <span class="welcome-briefing-icon"><AppIcon name="clipboard" :size="16" /></span>
              <div><strong>学习简报</strong><small>根据你的作业和订正情况整理</small></div>
              <router-link class="welcome-briefing-book" to="/student/mistakes">打开错题本 <AppIcon name="chevron-right" :size="13" /></router-link>
            </div>

            <div v-if="briefingAllDone(welcomeBriefing)" class="welcome-briefing-done">
              <span class="welcome-done-mark"><AppIcon name="check" :size="17" /></span>
              <div>
                <strong>太棒了，{{ auth.name }}！全部完成</strong>
                <p>作业和订正都完成了，暂时没有需要加固的知识点。可以把最近的题目独立重做一遍，巩固一下。</p>
              </div>
            </div>

            <!-- v0.9.0：欢迎屏简报改卡片组——与对话内简报卡同一套视觉（大数字+色块），
                 整卡可点：作业卡→作业列表、订正卡→订正页、加固卡→学习报告 -->
            <template v-else>
              <div class="brief-grid welcome-brief-grid">
                <div
                  v-if="welcomeBriefing.pending_assignments.length"
                  class="brief-stat-card brief-assign brief-clickable"
                  @click="router.push('/student/assignments')"
                >
                  <div class="brief-stat-head">
                    <span class="brief-big tnum">{{ welcomeBriefing.pending_assignments.length }}</span>
                    <span class="brief-stat-label">份作业待完成</span>
                  </div>
                  <div v-for="p in welcomeBriefing.pending_assignments.slice(0, 2)" :key="p.id" class="brief-item">
                    <span class="brief-item-main">
                      {{ p.title }}
                      <span class="badge badge-blue tnum">还剩 {{ p.remaining_count }} 题</span>
                      <span v-if="p.deadline" class="brief-item-sub">截止 {{ fmtDateTime(p.deadline) }}</span>
                    </span>
                    <button class="btn small" @click.stop="gotoAssignment(p)">继续</button>
                  </div>
                  <p class="brief-card-more">查看全部作业 <AppIcon name="chevron-right" :size="13" /></p>
                </div>

                <div
                  v-if="welcomeBriefing.pending_corrections_count"
                  class="brief-stat-card brief-corr brief-clickable"
                  @click="router.push('/student/corrections')"
                >
                  <div class="brief-stat-head">
                    <span class="brief-big tnum">{{ welcomeBriefing.pending_corrections_count }}</span>
                    <span class="brief-stat-label">处错题待订正</span>
                  </div>
                  <p class="brief-one-line" v-if="welcomeBriefing.pending_corrections_knowledge_points.length">
                    涉及知识点：{{ welcomeBriefing.pending_corrections_knowledge_points.join('、') }}
                  </p>
                  <p class="brief-card-more">去订正 <AppIcon name="chevron-right" :size="13" /></p>
                </div>

                <div
                  v-if="briefWeakDetails(welcomeBriefing).length"
                  class="brief-stat-card brief-weakstat brief-clickable"
                  @click="router.push('/student/report')"
                >
                  <div class="brief-stat-head">
                    <span class="brief-big tnum">{{ briefWeakDetails(welcomeBriefing).length }}</span>
                    <span class="brief-stat-label">个知识点需要加固</span>
                  </div>
                  <div class="brief-weak-list">
                    <p v-for="d in briefWeakDetails(welcomeBriefing).slice(0, 3)" :key="d.knowledge_point" class="brief-weak-line">
                      <span class="brief-weak-name">{{ d.knowledge_point }}</span>
                      <span class="brief-weak-meta">出错 <span class="tnum">{{ d.error_count }}</span> 次</span>
                    </p>
                  </div>
                  <p class="brief-card-more">去学习报告 <AppIcon name="chevron-right" :size="13" /></p>
                </div>
              </div>
              <p v-if="welcomeBriefing.recent_feedback" class="welcome-briefing-feedback">{{ sanitizeStudentCopy(welcomeBriefing.recent_feedback) }}</p>
            </template>
          </div>
        </section>

        <template v-else>
        <!-- 简报区（本轮小改）：简报从消息流抽出单独渲染——吸顶摘要条常驻对话区顶部，
             卡片组在条下方推开/收起；进入对话后默认收起，给消息流让位 -->
        <div v-if="welcomeBriefing" class="brief-bar">
          <span class="brief-bar-icon"><AppIcon name="clipboard" :size="13" /></span>
          <span class="brief-bar-label">学习简报</span>
          <span v-if="briefingAllDone(welcomeBriefing)" class="brief-bar-done">
            <AppIcon name="check" :size="13" /> 今日待办已清空
          </span>
          <span v-else class="brief-bar-items">
            <template v-for="(it, i) in briefSummaryItems" :key="it.key">
              <span v-if="i > 0" class="brief-bar-sep">·</span>
              <span class="brief-bar-item" :class="it.tone">{{ it.label }} <b class="tnum">{{ it.count }}</b></span>
            </template>
          </span>
          <button type="button" class="brief-bar-toggle" @click="toggleBriefCard">
            {{ briefCardOpen ? '收起' : '展开' }}
            <AppIcon name="chevron-down" :size="14" class="brief-bar-chevron" :class="{ open: briefCardOpen }" />
          </button>
        </div>
        <div v-if="welcomeBriefing" class="brief-expand" :class="{ open: briefCardOpen }">
          <div class="brief-expand-inner">
          <!-- AI 简报卡片区（v0.2.1 卡片化） -->
          <div class="ai-card briefing-card">
            <p class="ai-card-title"><AppIcon name="clipboard" :size="17" /> 学习简报</p>

            <!-- 全部完成：鼓励卡 -->
            <div v-if="briefingAllDone(welcomeBriefing)" class="brief-done">
              <span class="brief-done-icon"><AppIcon name="check" :size="22" /></span>
              <div>
                <p class="brief-done-title">太棒了，{{ auth.name }}！全部完成</p>
                <p class="brief-done-line">
                  作业都做完了，订正也全部搞定，暂时没有需要加固的知识点。复习建议：遮住答案把最近的题目独立重做一遍，巩固手感。
                </p>
              </div>
            </div>

            <template v-else>
              <p class="brief-hello">{{ auth.name }}，你好！这是你现在的进度：</p>

              <div class="brief-grid">
                <!-- 未完成作业卡 -->
                <div v-if="welcomeBriefing.pending_assignments.length" class="brief-stat-card brief-assign">
                  <div class="brief-stat-head">
                    <span class="brief-big tnum">{{ welcomeBriefing.pending_assignments.length }}</span>
                    <span class="brief-stat-label">份作业还没完成</span>
                  </div>
                  <div v-for="p in welcomeBriefing.pending_assignments" :key="p.id" class="brief-item">
                    <span class="brief-item-main">
                      {{ p.title }}
                      <span v-if="p.mode === 'offline'" class="badge badge-amber">线下练习</span>
                      <span class="badge badge-blue tnum">还剩 {{ p.remaining_count }} 题</span>
                      <span v-if="p.mode === 'offline'" class="brief-item-sub">
                        <template v-if="p.workbook_title">{{ p.workbook_title }}</template>
                        <template v-if="p.page_range"> · {{ p.page_range }}</template>
                        <template v-if="p.deadline"> · 截止 {{ fmtDateTime(p.deadline) }}</template>
                      </span>
                    </span>
                    <button class="btn small" @click="gotoAssignment(p)">去完成</button>
                  </div>
                </div>

                <!-- 待订正卡 -->
                <div v-if="welcomeBriefing.pending_corrections_count" class="brief-stat-card brief-corr">
                  <div class="brief-stat-head">
                    <span class="brief-big tnum">{{ welcomeBriefing.pending_corrections_count }}</span>
                    <span class="brief-stat-label">处错题还没订正</span>
                  </div>
                  <p class="brief-one-line" v-if="welcomeBriefing.pending_corrections_knowledge_points.length">
                    涉及知识点：{{ welcomeBriefing.pending_corrections_knowledge_points.join('、') }}
                  </p>
                  <router-link to="/student/corrections"><button class="btn small secondary">去订正</button></router-link>
                </div>
              </div>

              <!-- 需加固知识点小卡 -->
              <div v-if="briefWeakDetails(welcomeBriefing).length" class="brief-weak">
                <p class="brief-label">需要加固的知识点</p>
                <div class="brief-weak-grid">
                  <div v-for="d in briefWeakDetails(welcomeBriefing)" :key="d.knowledge_point" class="brief-weak-card">
                    <span class="brief-weak-name">{{ d.knowledge_point }}</span>
                    <span class="brief-weak-meta">
                      出错 <span class="tnum">{{ d.error_count }}</span> 次
                      <template v-if="d.last_error_at"> · 最近 {{ fmtDate(d.last_error_at) }}</template>
                    </span>
                  </div>
                </div>
              </div>

              <!-- 最近动态：一行小字 -->
              <p v-if="welcomeBriefing.recent_feedback" class="brief-recent">
                最近动态：{{ sanitizeStudentCopy(welcomeBriefing.recent_feedback) }}
              </p>
            </template>
          </div>
          </div>
        </div>

        <div v-for="msg in visibleMessages" :key="msg.id" class="msg-row" :class="msg.side">
          <div v-if="msg.side === 'ai'" class="msg-avatar"><AppIcon name="sparkles" :size="16" /></div>

          <!-- AI 普通文本 -->
          <div v-if="msg.kind === 'text' && msg.side === 'ai'" class="bubble ai-bubble">
            <div class="ai-message-text">
              <AppIcon v-if="msg.pending" name="spinner" :size="16" class="spin" />
              <div v-if="msg.streaming" class="ai-message-markdown ai-message-streaming" v-html="renderAssistantMarkdown(msg.text)"></div>
              <div v-else class="ai-message-markdown" v-html="renderAssistantMarkdown(msg.text)"></div>
            </div>
            <div v-if="msg.mistakeSync" class="photo-mistake-sync" :class="{ 'is-pending': msg.mistakeSync.pendingReview, 'is-deferred': msg.mistakeSync.deferred, 'is-empty': !msg.mistakeSync.errorCount && !msg.mistakeSync.deferred, 'is-error': Boolean(msg.mistakeSync.error) }">
              <AppIcon :name="msg.mistakeSync.error ? 'alert' : msg.mistakeSync.deferred ? 'history' : msg.mistakeSync.errorCount ? 'check' : 'help'" :size="15" />
              <span v-if="msg.mistakeSync.error" class="mistake-sync-error">{{ msg.mistakeSync.error }}</span>
              <span v-else-if="msg.mistakeSync.deferred">本次作答已保存，作业截止后统一批改</span>
              <span v-else-if="msg.mistakeSync.errorCount">
                已将 {{ msg.mistakeSync.errorCount }} 条诊断记录同步到错题本和订正区
                <small v-if="msg.mistakeSync.pendingReview">本题已提交老师复核</small>
              </span>
              <span v-else>本次没有发现错题，未加入错题本</span>
              <router-link v-if="msg.mistakeSync.errorCount" to="/student/mistakes">查看错题本</router-link>
            </div>
            <button v-if="msg.relatedMistake" type="button" class="related-mistake-link" @click="openRelatedMistake(msg.relatedMistake)">
              回看以前错过的同类题 <AppIcon name="chevron-right" :size="14" />
            </button>
            <button v-if="msg.retryPrompt || msg.retryVision || msg.retryDiagnosis || msg.retrySave" class="btn small secondary retry-explanation" :disabled="msg.pending" @click="retryExplanation(msg)">
              {{ msg.pending ? '正在重试…' : msg.retrySave && !msg.retryVision && !msg.retryDiagnosis ? '重试保存对话' : msg.retryVision && msg.retryDiagnosis ? '重试识别和讲解' : msg.retryDiagnosis ? '重试作业识别' : '重试讲解' }}
            </button>
            <div v-if="msg.captureId" class="photo-capture-action">
              <span v-if="msg.saved">已加入错题本</span>
              <button v-else class="btn small secondary" :disabled="msg.savingCapture" @click="savePhotoQuestion(msg)">
                {{ msg.savingCapture ? '正在收录…' : '加入错题本' }}
              </button>
            </div>
          </div>

          <!-- AI 错误提示 -->
          <div v-else-if="msg.kind === 'error'" class="bubble error-bubble">
            <AppIcon name="alert" :size="16" /> {{ msg.text }}
            <button v-if="msg.retryPrompt || msg.retryVision || msg.retryDiagnosis || msg.retrySave" class="btn small secondary retry-explanation" :disabled="msg.pending" @click="retryExplanation(msg)">
              {{ msg.pending ? '正在重试…' : msg.retrySave && !msg.retryVision && !msg.retryDiagnosis ? '重试保存对话' : msg.retryVision && msg.retryDiagnosis ? '重试识别和讲解' : msg.retryDiagnosis ? '重试作业识别' : '重试讲解' }}
            </button>
            <div v-if="msg.captureId" class="photo-capture-action">
              <span v-if="msg.saved">已加入错题本</span>
              <button v-else class="btn small secondary" :disabled="msg.savingCapture" @click="savePhotoQuestion(msg)">
                {{ msg.savingCapture ? '正在收录…' : '加入错题本' }}
              </button>
            </div>
          </div>

          <!-- 转写卡片 -->
          <div v-else-if="msg.kind === 'transcribe'" class="ai-card">
            <p class="ai-card-title"><AppIcon name="camera" :size="17" /> 照片转写结果</p>
            <p class="hint" style="margin-bottom: 10px">
              我先把照片里的内容转写出来，认错的地方可以直接改，确认无误后点「确认批改」。
            </p>
            <label class="mini-label">题干</label>
            <input v-model="msg.questionText" type="text" :disabled="msg.confirmed" />
            <label class="mini-label">解题步骤（每行一步，不用写题干）</label>
            <div v-for="(s, i) in msg.steps" :key="i" class="transcribe-step">
              <span class="tnum step-idx">{{ i + 1 }}</span>
              <input v-model="msg.steps[i]" type="text" :disabled="msg.confirmed" />
              <button class="icon-btn" title="删除这一步" :disabled="msg.confirmed" @click="msg.steps.splice(i, 1)">
                <AppIcon name="x" :size="16" />
              </button>
            </div>
            <button class="btn small secondary inline-icon" :disabled="msg.confirmed" @click="msg.steps.push('')">
              <AppIcon name="plus" :size="14" /> 添加一步
            </button>
            <label class="mini-label">这道题对应课本里的哪一题</label>
            <select v-model="msg.questionId" :disabled="msg.confirmed">
              <option :value="null">请选择…</option>
              <option v-for="q in allMathQuestions" :key="q.id" :value="q.id">
                {{ q.assignmentTitle }} · {{ q.stem }}
              </option>
            </select>
            <div class="toolbar" style="margin: 14px 0 0">
              <button class="btn" :disabled="msg.confirmed || msg.submitting" @click="confirmTranscribe(msg)">
                {{ msg.confirmed ? '已批改' : msg.submitting ? '批改中…' : '确认批改' }}
              </button>
            </div>
          </div>

          <!-- 诊断卡片 -->
          <div v-else-if="msg.kind === 'diagnosis' && msg.result" class="ai-card">
            <p class="ai-card-title">
              <AppIcon name="check" :size="17" /> 批改结果
              <span class="badge badge-blue">{{ questionStem(msg.result.question_id) }}</span>
            </p>
            <!-- 低置信错因仍立即展示并进入订正流程，教师审核并行进行 -->
            <div v-if="msg.result.status === 'pending_review'" class="review-pending-box">
              <span class="review-pending-icon"><AppIcon name="history" :size="17" /></span>
              <div>
                <p class="review-pending-title">错题已同步加入错题本和订正区</p>
                <p class="review-pending-sub">老师也会复核这次低置信度判断；如需调整，错因会同步更新。</p>
              </div>
            </div>
            <template v-if="msg.result.steps.length || msg.result.errors.length">
            <div
              v-for="st in msg.result.steps"
              :key="st.seq"
              class="diag-step"
              :class="{ 'first-error': st.status === 'error', correct: st.status === 'ok' }"
            >
              <span class="diag-icon" :class="st.status"><AppIcon :name="stepIcon(st.status)" :size="15" /></span>
              <div class="diag-step-main">
                <div class="step-title">{{ st.seq === 0 ? '题干' : `步骤 ${st.seq}` }} · {{ STEP_STATUS_TEXT[st.status] }}</div>
                <p>{{ st.text }}</p>
              </div>
            </div>

            <template v-if="msg.result.errors.length">
              <div v-for="e in msg.result.errors" :key="e.id" class="error-item">
                <p>
                  <ErrorTypeBadge :type="e.error_type" />
                  <span v-if="e.is_stubborn" class="badge badge-amber">需要加固的知识点</span>
                  <span v-else class="badge badge-green">已注意，继续保持</span>
                </p>
                <p class="encourage">
                  {{ e.is_stubborn ? '这个知识点还需要再加固一下，多练几道同类题会有帮助。' : '这是一次偶发的小失误，下次细心一点就好。' }}
                </p>
                <p class="detail"><strong>解析：</strong>{{ sanitizeStudentCopy(e.detail) }}</p>
                <div class="toolbar" style="margin-top: 8px; margin-bottom: 0">
                  <router-link to="/student/corrections"><button class="btn small secondary">去订正这道题</button></router-link>
                </div>
              </div>
            </template>
            <p v-else class="ok-line"><AppIcon name="check" :size="16" /> 太棒了，这道题全部正确，继续保持！</p>

            <!-- 追问（v0.4.0）：先想一想，再看解析 -->
            <div v-if="msg.result.follow_up_question" class="followup-box">
              <span class="followup-icon"><AppIcon name="lightbulb" :size="16" /></span>
              <p><b>想一想：</b>{{ msg.result.follow_up_question }}</p>
            </div>
            </template>
          </div>

          <!-- 用户消息 -->
          <div v-else-if="msg.side === 'user' && msg.kind === 'image'" class="user-image">
            <div class="user-image-card">
              <p v-if="msg.text" class="user-image-prompt">{{ msg.text }}</p>
              <button class="user-image-trigger" type="button" :aria-label="`放大${msg.fileName || '作业照片'}`" @click="openImagePreview(msg.url, msg.fileName || '作业照片')">
                <img :src="msg.url" :alt="msg.fileName || '作业照片'" />
              </button>
              <button class="user-image-caption" type="button" @click="openImagePreview(msg.url, msg.fileName || '作业照片')">
                {{ msg.fileName || '作业照片' }} · 点击查看大图
              </button>
            </div>
          </div>
          <div v-else-if="msg.side === 'user'" class="bubble user-bubble">{{ msg.text }}</div>
        </div>

        <!-- 建议气泡（v0.6.0）：只挂最新一轮对话回复，stagger 淡入上浮，点击直接发送 -->
        <div v-if="suggestions.length && !chatSending" class="suggest-row">
          <button
            v-for="(s, i) in suggestions"
            :key="s"
            class="suggest-chip"
            :style="{ animationDelay: `${i * 70}ms` }"
            @click="sendChat(s)"
          >
            {{ s }}
          </button>
        </div>

        <div v-if="loadingInit" class="loading">正在为你准备学习简报…</div>
        </template>
      </div>
    </div>

    <!-- 输入区（v0.3.0：文本聊天接学习助手 Agent + 拍照批改并存；
         v0.8.1 恢复 v0.6.2 悬浮毛玻璃卡：悬浮在消息区底部，消息从卡下滚过） -->
    <div class="chat-composer" :class="{ 'chat-composer-welcome': isWelcomeScreen }">
      <div class="chat-inner">
        <div class="composer-panel">
          <div v-if="selectedImage && selectedImageUrl" class="composer-image-preview">
            <button class="composer-image-open" type="button" aria-label="放大待发送图片" @click="openImagePreview(selectedImageUrl, selectedImage.name || '待发送图片')">
              <img :src="selectedImageUrl" :alt="selectedImage.name || '待发送图片'" />
            </button>
            <button class="composer-image-remove" type="button" aria-label="移除图片" title="移除图片" :disabled="chatSending" @click="clearSelectedImage">
              <AppIcon name="x" :size="15" />
            </button>
          </div>
          <textarea
            v-model="chatInput"
            class="chat-text-input"
            :class="{ 'chat-text-input-welcome': isWelcomeScreen }"
            rows="1"
            :placeholder="isWelcomeScreen ? '有什么想问的，或说说你正在学习的内容…' : '输入你的问题，回车发送'"
            :disabled="chatSending"
            @keydown.enter.exact.prevent="sendChat()"
          ></textarea>
          <div class="composer-bottom-row">
            <input ref="fileRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onFileChange" />
            <div class="composer-tools">
              <button class="composer-photo-btn" type="button" aria-label="拍照批改" title="拍照批改" :disabled="busy" @click="fileRef?.click()">
                <AppIcon name="camera" :size="18" />
              </button>
              <span v-if="selectedQuestion" class="composer-context"><AppIcon name="clipboard" :size="13" /> {{ selectedQuestion.stem }}</span>
            </div>
            <button class="btn send-btn" type="button" :aria-label="selectedImage ? '发送图片' : '发送'" :title="selectedImage ? '发送图片' : '发送'" :disabled="chatSending || (!chatInput.trim() && !selectedImage)" @click="sendChat()">
              <AppIcon name="send" :size="17" />
            </button>
          </div>
        </div>
      </div>
    </div>
    </div>
    <div v-if="imagePreview" class="image-lightbox" role="dialog" aria-modal="true" aria-label="图片预览" @click.self="closeImagePreview">
      <button class="image-lightbox-close" type="button" aria-label="关闭图片预览" title="关闭" @click="closeImagePreview">
        <AppIcon name="x" :size="21" />
      </button>
      <img :src="imagePreview.url" :alt="imagePreview.alt" />
    </div>
    <PreviousMistakeModal :mistake="selectedRelatedMistake" @close="selectedRelatedMistake = null" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useStudentStore } from '../../stores/student'
import type {
  AgentHistoryItem,
  Assignment,
  PendingAssignment,
  PhotoReviewResult,
  Question,
  RelatedMistake,
  StepStatus,
  StudentBriefing,
  SubmissionResult,
  WeakPointDetail
} from '../../api/types'
import { STEP_STATUS_TEXT } from '../../api/types'
import { sanitizeStudentCopy } from '../../utils/errorType'
import AppIcon from '../../components/icons/AppIcon.vue'
import type { IconName } from '../../components/icons/paths'
import ErrorTypeBadge from '../../components/ErrorTypeBadge.vue'
import PreviousMistakeModal from '../../components/PreviousMistakeModal.vue'

const auth = useAuthStore()
const student = useStudentStore()
const route = useRoute()
const router = useRouter()

const assistantMarkdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: false,
  typographer: false
})

function renderAssistantMarkdown(text: string): string {
  return assistantMarkdown.render(text || '')
}

// ---------- 对话消息 ----------
interface ChatMsg {
  id: number
  side: 'ai' | 'user'
  kind: 'briefing' | 'text' | 'image' | 'transcribe' | 'diagnosis' | 'error'
  text: string
  url: string
  fileName?: string
  briefing: StudentBriefing | null
  questionText: string
  steps: string[]
  questionId: number | null
  confirmed: boolean
  submitting: boolean
  pending: boolean
  streaming?: boolean
  result: SubmissionResult | null
  captureId: number | null
  retryPrompt?: string
  retrySafeToolsOnly?: boolean
  retryVision?: boolean
  retryDiagnosis?: boolean
  retrySave?: boolean
  saved: boolean
  savingCapture: boolean
  relatedMistake: RelatedMistake | null
  mistakeSync?: { errorCount: number; pendingReview: boolean; deferred: boolean; error?: string } | null
}

const messages = ref<ChatMsg[]>([])
type PendingPhotoRetry = {
  file: File
  prompt: string
  visionQuestion: string
  questionId: number | null
  sessionId: number
  userImage: ChatMsg
  assistantSaved: boolean
  assistantText?: string
}
const pendingPhotoRetries = new Map<number, PendingPhotoRetry>()
let seq = 0
function pushMsg(partial: Partial<ChatMsg>): ChatMsg {
  const msg: ChatMsg = {
    id: ++seq,
    side: 'ai',
    kind: 'text',
    text: '',
    url: '',
    fileName: '',
    briefing: null,
    questionText: '',
    steps: [],
    questionId: null,
    confirmed: false,
    submitting: false,
    pending: false,
    result: null,
    captureId: null,
    saved: false,
    savingCapture: false,
    relatedMistake: null,
    ...partial
  }
  messages.value.push(msg)
  scrollToBottom()
  // 返回数组中的响应式代理；返回原始对象会让异步流式文本更新绕过 Vue，
  // 最终只在其他状态变化时整段刷新出来。
  return messages.value[messages.value.length - 1]
}

// ---------- 题目选择（仅数学题可拍照批改） ----------
interface FlatQuestion extends Question {
  assignmentTitle: string
}
const assignments = ref<Assignment[]>([])
const questionsByAssignment = ref<Record<number, Question[]>>({})
const flatQuestions = ref<FlatQuestion[]>([])
const assignmentId = ref<number | ''>('')
const questionId = ref<number | ''>('')
const doneQids = ref<Set<number>>(new Set())

const currentQuestions = computed(
  () => (questionsByAssignment.value[Number(assignmentId.value)] ?? []).filter((q) => q.subject === 'math')
)
const selectedQuestion = computed(
  () => flatQuestions.value.find((q) => q.id === Number(questionId.value)) ?? null
)
const allMathQuestions = computed(() => flatQuestions.value.filter((q) => q.subject === 'math'))

function onAssignmentChange() {
  const qs = currentQuestions.value
  questionId.value = qs.length ? qs[0].id : ''
}

function questionStem(qid: number): string {
  return flatQuestions.value.find((q) => q.id === qid)?.stem ?? ''
}

// ---------- 输入区 ----------
const fileRef = ref<HTMLInputElement | null>(null)
const selectedImage = ref<File | null>(null)
const selectedImageUrl = ref('')
const imagePreview = ref<{ url: string; alt: string } | null>(null)
const selectedRelatedMistake = ref<RelatedMistake | null>(null)

function openRelatedMistake(mistake: RelatedMistake) {
  selectedRelatedMistake.value = mistake
}
const imageObjectUrls = new Set<string>()
const bodyRef = ref<HTMLElement | null>(null)
let scrollFrame: number | null = null
const loadingInit = ref(true)
const welcomeBriefing = computed(() => messages.value.find((msg) => msg.kind === 'briefing')?.briefing ?? null)
const isWelcomeScreen = computed(
  () => !loadingInit.value && !messages.value.some((msg) => msg.side === 'user' || (msg.kind !== 'briefing' && msg.text.trim()))
)

// ---------- 简报收起（本轮小改） ----------
// 判定条件：会话里出现过用户消息（hasConversation）→ 已进入对话态。
// 来源包括两种：本页刚发送的消息（sendChat / 拍照批改都会 push 用户消息）、
// 以及打开历史会话时从后端恢复出的 role=user 消息（挂载 fetchAgentHistory、
// 会话同步 watch 的 fetchSessionMessages 两条路径）。
// 进入对话态后简报卡片组默认收起、只留吸顶摘要条；briefManual 是用户手动
// 展开/收起的选择（null = 跟随默认）。手动展开后不会被后续发送自动收起
// （不打扰用户正在看的卡片），切换会话时在会话同步 watch 里复位为 null。
const briefManual = ref<boolean | null>(null)
const hasConversation = computed(() => messages.value.some((m) => m.side === 'user'))
const briefCardOpen = computed(() => briefManual.value ?? !hasConversation.value)
function toggleBriefCard() {
  briefManual.value = !briefCardOpen.value
}
/** 摘要条三项（只列非零项，顺序：作业 → 订正 → 加固；全清走模板里的清空文案） */
const briefSummaryItems = computed(() => {
  const b = welcomeBriefing.value
  if (!b) return [] as { key: string; label: string; count: number; tone: string }[]
  const items: { key: string; label: string; count: number; tone: string }[] = []
  if (b.pending_assignments.length)
    items.push({ key: 'assign', label: '未完成作业', count: b.pending_assignments.length, tone: '' })
  if (b.pending_corrections_count)
    items.push({ key: 'corr', label: '待订正', count: b.pending_corrections_count, tone: 'corr' })
  const weak = briefWeakDetails(b).length
  if (weak) items.push({ key: 'weak', label: '需加固知识点', count: weak, tone: 'weak' })
  return items
})
/** 对话消息流（简报消息已从循环抽出、单独在上方简报区渲染） */
const visibleMessages = computed(() => messages.value.filter((m) => m.kind !== 'briefing'))

/** 进入对话态的瞬间拉一次最新简报：本页发送/批改后原本不刷新简报，
 *  摘要条若沿用挂载时的旧数字会不准；只在「收起态切换」这一刻补拉 */
async function refreshBriefing() {
  try {
    const b = await student.fetchBriefing()
    const m = messages.value.find((x) => x.kind === 'briefing')
    if (m) m.briefing = b
  } catch (e) {
    console.error(e)
  }
}
watch(hasConversation, (now, prev) => {
  if (now && !prev) void refreshBriefing()
})
const busy = computed(() => messages.value.some((m) => m.pending || m.submitting))

function scrollToBottom() {
  if (scrollFrame !== null) return
  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = null
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function errDetail(e: unknown): string {
  const error = e as { response?: { data?: { detail?: string } }; message?: string }
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return typeof error?.message === 'string' ? error.message : ''
}

function stepIcon(s: StepStatus): IconName {
  return { stem: 'file', ok: 'check', error: 'x', unparseable: 'help', skipped: 'minus' }[s] as IconName
}

function fmtDate(t: string): string {
  return t.replace('T', ' ').slice(0, 10)
}
function fmtDateTime(t: string): string {
  return t.replace('T', ' ').slice(0, 16)
}

// ---------- 简报 ----------
function briefingAllDone(b: StudentBriefing): boolean {
  return (
    b.pending_assignments.length === 0 &&
    b.pending_corrections_count === 0 &&
    b.weak_points.length === 0
  )
}

/** 需加固知识点明细：优先用后端 weak_point_details，缺失时用 weak_points 名称兜底 */
function briefWeakDetails(b: StudentBriefing): WeakPointDetail[] {
  if (b.weak_point_details?.length) return b.weak_point_details
  return b.weak_points.map((kp) => ({ knowledge_point: kp, error_count: 0, last_error_at: null }))
}

// 简报「去完成」：选中该作业里第一道还没做的数学题。
// v0.13.1 按模式分流（此前一律引导拍照，线上作业也被说成拍照上传，与实际作答方式不符）：
// 线上作业是在线作答——直接跳交作业页的做题板并定位到这道题；线下练习册才引导拍照。
async function gotoAssignment(p: PendingAssignment) {
  assignmentId.value = p.id
  const qs = currentQuestions.value
  const target = qs.find((q) => !doneQids.value.has(q.id)) ?? qs[0]
  questionId.value = target ? target.id : ''
  if (!target) return
  if (p.mode === 'online') {
    router.push({ path: '/student/submit', query: { assignment_id: p.id, q: target.id } })
    return
  }
  pushMsg({
    side: 'ai',
    kind: 'text',
    text: `已帮你选中《${p.title}》的题目「${target.stem}」，点下方「拍照批改」，拍下你的作答过程就可以啦。`
  })
  scrollToBottom()
}

// ---------- 学习助手文本聊天（v0.3.0：LangGraph Agent） ----------
const chatInput = ref('')
const chatSending = ref(false)

function createImageUrl(file: File): string {
  const url = URL.createObjectURL(file)
  imageObjectUrls.add(url)
  return url
}

function clearSelectedImage() {
  if (selectedImageUrl.value) {
    URL.revokeObjectURL(selectedImageUrl.value)
    imageObjectUrls.delete(selectedImageUrl.value)
  }
  selectedImage.value = null
  selectedImageUrl.value = ''
}

function openImagePreview(url: string, alt: string) {
  if (url) imagePreview.value = { url, alt }
}

function closeImagePreview() {
  imagePreview.value = null
}

function onImagePreviewKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && imagePreview.value) closeImagePreview()
}

onUnmounted(() => {
  if (scrollFrame !== null) window.cancelAnimationFrame(scrollFrame)
  window.removeEventListener('keydown', onImagePreviewKeydown)
  imageObjectUrls.forEach((url) => URL.revokeObjectURL(url))
  imageObjectUrls.clear()
})

// ---------- 会话（v0.6.2 状态层；v0.8.1 合并修复）：会话列表与当前会话归 store，
// 与左侧栏会话区共用同一份状态；本页不再自持会话状态，侧栏操作改 store.sessionView，
// 本页 watch 其 seq 变化后同步重渲染（同步逻辑在下方「会话查看同步」段） ----------

// ---------- 建议气泡（v0.6.0）：只存最新一轮回复的建议 ----------
const suggestions = ref<string[]>([])

/** 把简报卡作为第一条消息放回对话区（新对话/切换会话后复用） */
async function prependBriefing() {
  try {
    const briefing = await student.fetchBriefing()
    messages.value.unshift({
      id: ++seq,
      side: 'ai',
      kind: 'briefing',
      text: '',
      url: '',
      briefing,
      questionText: '',
      steps: [],
      questionId: null,
      confirmed: false,
      submitting: false,
      pending: false,
      result: null,
      captureId: null,
      saved: false,
      savingCapture: false,
      relatedMistake: null
    })
  } catch (e) {
    console.error(e)
  }
}

// ---------- 会话查看同步（v0.8.1，与 TeacherChat 同一套）：侧栏新建/点选/删除当前会话
// → store.sessionView.seq 递增 → 本页重渲染。学生端与教师端的差异只有一点：
// 简报卡始终保留置顶，会话消息接在简报下方（与原 switchSession 行为一致）。
// fresh=true 表示刚新建的空会话；id=null 表示会话已删光；两者都回到「只剩简报卡」的欢迎态。
let appliedViewSeq = 0
function restoreHistoryMessage(h: AgentHistoryItem) {
  if (h.role === 'user' && h.image_url) {
    const text = h.content
      .replace(/^上传了一张作业照片。?\s*/, '')
      .replace(/^补充说明：/, '')
    pushMsg({
      side: 'user',
      kind: 'image',
      text,
      fileName: h.image_name || '作业照片',
      url: h.image_url
    })
    return
  }
  pushMsg({
    side: h.role === 'user' ? 'user' : 'ai',
    kind: 'text',
    text: h.content,
    relatedMistake: h.related_mistake ?? null
  })
}
watch(
  () => student.sessionView.seq,
  async (seqVal) => {
    if (seqVal === appliedViewSeq) return
    appliedViewSeq = seqVal
    const view = student.sessionView
    clearSelectedImage()
    suggestions.value = []
    briefManual.value = null
    messages.value = messages.value.filter((m) => m.kind === 'briefing')
    if (!messages.value.length) await prependBriefing()
    if (!view.fresh && view.id != null) {
      try {
        const rows = await student.fetchSessionMessages(view.id)
        rows.forEach(restoreHistoryMessage)
      } catch (e) {
        pushMsg({ side: 'ai', kind: 'error', text: '打开这条对话失败：' + (errDetail(e) || '请稍后重试。') })
        console.error(e)
      }
    }
    scrollToBottom()
  }
)

async function sendChat(raw?: string) {
  const text = (typeof raw === 'string' ? raw : chatInput.value).trim()
  const image = selectedImage.value
  if ((!text && !image) || chatSending.value) return
  if (text.length > 2000) {
    pushMsg({ side: 'ai', kind: 'error', text: '这条消息有点太长了（最多 2000 字），拆成两条发给我吧。' })
    return
  }
  if (image) {
    chatInput.value = ''
    clearSelectedImage()
    suggestions.value = []
    await sendPhotoReview(image, text)
    return
  }
  chatInput.value = ''
  suggestions.value = []
  const previousQuestion = [...messages.value].reverse().find((item) => item.side === 'user' && item.kind === 'text')?.text ?? ''
  pushMsg({ side: 'user', kind: 'text', text })
  const wait = pushMsg({ side: 'ai', kind: 'text', text: '正在思考…', pending: true })
  chatSending.value = true
  try {
    await student.ensureActiveChatSession()
    const saveIntent = /加入|收录|保存|放(?:到|进|入)?|加(?:到|进|入)|记(?:到|进)|收藏/.test(text) && /错题本|错题/.test(text)
    const refersToPrevious = /刚才|上一题|前面那题|之前那题/.test(text)
    const cleanedQuestion = text.replace(/[，,。 ]*(?:顺便)?(?:请)?(?:把)?(?:这道题|这题)?(?:加入|收录|保存|放(?:到|进|入)?|加(?:到|进|入)|记(?:到|进)|收藏)(?:错题本|错题)(?:里|中)?[。！!]?/g, '').trim()
    const containsQuestion = /[=+\-×÷?？]/.test(cleanedQuestion) || cleanedQuestion.length > 10
    const pendingCapture = [...messages.value].reverse().find((item) => item.captureId && !item.saved)
    if (pendingCapture && saveIntent && !containsQuestion && !refersToPrevious) {
      await student.savePhotoCapture(pendingCapture.captureId!, pendingCapture.text)
      pendingCapture.saved = true
      wait.text = '已经把刚才的题目加入错题本了。'
      await student.loadSessions(true)
      return
    }
    if (saveIntent) {
      const questionToSave = refersToPrevious || !containsQuestion
        ? previousQuestion
        : cleanedQuestion
      if (questionToSave) {
        await student.saveTextQuestion(questionToSave)
        wait.text = '已经把这道题加入错题本了。'
        await student.loadSessions(true)
        if (refersToPrevious || !containsQuestion) return
      }
    }
    await streamAssistantReply(wait, text)
  } catch (e) {
    wait.kind = 'error'
    wait.text = '发送失败：' + (errDetail(e) || '请稍后重试。')
    console.error(e)
  } finally {
    wait.pending = false
    chatSending.value = false
    scrollToBottom()
  }
}

async function streamAssistantReply(
  wait: ChatMsg,
  prompt: string,
  persistUserMessage = true,
  safeToolsOnly = false,
  relatedMistakeErrorId?: number | null
) {
  let firstText = true
  wait.text = '正在生成回复…'
  wait.pending = true
  wait.streaming = true
  try {
    const result = await student.agentChatStream(prompt, student.activeSessionId, (text) => {
      if (firstText) {
        wait.text = ''
        wait.pending = false
        firstText = false
      }
      wait.text += text
      scrollToBottom()
    }, persistUserMessage, safeToolsOnly, relatedMistakeErrorId)
    wait.pending = false
    wait.text = result.reply
    wait.relatedMistake = result.related_mistake ?? null
    wait.retryPrompt = undefined
    wait.retrySafeToolsOnly = undefined
    if (result.session_id) student.setActiveSession(result.session_id)
    suggestions.value = result.suggestions ?? []
    // 刷新侧栏会话列表：首问生成标题、顺序按最近更新重排。
    student.loadSessions(true)
  } finally {
    wait.pending = false
    wait.streaming = false
  }
}

// ---------- 拍照批改 ----------
async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    pushMsg({ side: 'ai', kind: 'error', text: '这张图片格式不对，请上传 jpg / png / webp 格式的作业照片。' })
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    pushMsg({ side: 'ai', kind: 'error', text: '图片太大了（超过 10MB），请压缩后再试。' })
    return
  }
  clearSelectedImage()
  selectedImage.value = file
  selectedImageUrl.value = createImageUrl(file)
}

function applyPhotoReviewResult(wait: ChatMsg, userImage: ChatMsg, res: PhotoReviewResult) {
  if (res.image_url) userImage.url = res.image_url
  if (res.session_id) student.setActiveSession(res.session_id)
  wait.questionText = res.question_text
  wait.steps = [...res.steps]
  wait.relatedMistake = res.related_mistake ?? null
  wait.retryDiagnosis = false

  if (res.mode === 'answer') {
    wait.captureId = res.capture_id
    wait.mistakeSync = null
  } else if (res.mode === 'diagnosis' && res.diagnosis) {
    wait.mistakeSync = {
      errorCount: res.diagnosis.errors.length,
      pendingReview: res.diagnosis.status === 'pending_review',
      deferred: res.diagnosis.status === 'deferred'
    }
  }
}

function markPhotoReviewFailure(wait: ChatMsg, reason: unknown) {
  wait.mistakeSync = {
    errorCount: 0,
    pendingReview: false,
    deferred: false,
    error: '自动批改暂未完成，错题尚未确认入库。可以重试作业识别。'
  }
  wait.retryDiagnosis = true
  console.error(reason)
}

async function streamVisionReply(wait: ChatMsg, file: File, question: string): Promise<string> {
  let firstText = true
  wait.text = ''
  wait.pending = true
  wait.streaming = true
  try {
    const reply = await student.agentVisionChatStream(file, question, (text) => {
      if (firstText) {
        wait.text = ''
        wait.pending = false
        firstText = false
      }
      wait.text += text
      scrollToBottom()
    })
    wait.text = reply
    return reply
  } finally {
    wait.pending = false
    wait.streaming = false
  }
}

async function sendPhotoReview(file: File, prompt: string) {
  suggestions.value = []
  const userImage = pushMsg({ side: 'user', kind: 'image', text: prompt, fileName: file.name, url: createImageUrl(file) })
  const wait = pushMsg({ side: 'ai', kind: 'text', text: '正在分析原图并检查作答…', pending: true })
  chatSending.value = true
  try {
    await student.ensureActiveChatSession()
    const sessionId = student.activeSessionId
    if (!sessionId) throw new Error('当前对话暂不可用，请新建对话后重试。')
    const questionId = selectedQuestion.value?.id ?? null
    const questionContext = selectedQuestion.value?.stem ?? ''
    const visionQuestion = [
      prompt,
      questionContext ? `当前作业题干参考：${questionContext}` : ''
    ].filter(Boolean).join('\n').slice(0, 2000)
    const retry: PendingPhotoRetry = { file, prompt, visionQuestion, questionId, sessionId, userImage, assistantSaved: false }
    pendingPhotoRetries.set(wait.id, retry)

    // 原图讲解与作业诊断并发：讲解请求直接携带图片，诊断请求独立保存错题/审核记录。
    const diagnosisTask = student.reviewPhoto(
      file, questionId, '', sessionId, true, prompt
    ).then((result) => {
      // 批改与视觉讲解并发；批改一完成就更新错题/审核状态，不等待讲解流结束。
      applyPhotoReviewResult(wait, userImage, result)
      void student.loadSessions(true)
      return result
    }).catch((reason: unknown) => {
      markPhotoReviewFailure(wait, reason)
      throw reason
    })
    const visionTask = streamVisionReply(wait, file, visionQuestion)
    const [diagnosisResult, visionResult] = await Promise.allSettled([diagnosisTask, visionTask])

    const photoResult = diagnosisResult.status === 'fulfilled' ? diagnosisResult.value : null

    if (visionResult.status === 'fulfilled') {
      wait.retryVision = false
      retry.assistantText = visionResult.value
      try {
        await student.appendAgentAssistantMessage(
          sessionId,
          visionResult.value,
          photoResult?.related_mistake?.id
        )
        retry.assistantSaved = true
        void student.loadSessions(true)
      } catch (saveError) {
        wait.text += '\n\n这次讲解已显示，但暂时没能保存到历史对话。'
        wait.retrySave = true
        console.error(saveError)
      }
    } else {
      const partial = wait.text.trim()
      wait.text = partial
        ? `${partial}\n\n视觉讲解中断了，可以点击重试继续生成。`
        : '视觉模型暂时无法生成讲解，可以点击重试；作业诊断仍会单独处理。'
      wait.retryVision = true
      console.error(visionResult.reason)
    }

    if (photoResult?.mode === 'answer' && photoResult.capture_id) {
      const saveQuestion = /加入|收录|保存|放(?:到|进|入)?|加(?:到|进|入)|记(?:到|进)|收藏/.test(prompt) && /错题本|错题/.test(prompt)
      if (saveQuestion) {
        try {
          await student.savePhotoCapture(photoResult.capture_id, wait.text)
          wait.saved = true
          void student.loadSessions(true)
        } catch (saveError) {
          wait.text += '\n题目已经解答，但加入错题本失败，请稍后点下方按钮重试。'
          console.error(saveError)
        }
      }
    }

    if (!wait.retryVision && !wait.retryDiagnosis && !wait.retrySave && retry.assistantSaved) {
      pendingPhotoRetries.delete(wait.id)
    }
  } catch (err) {
    wait.kind = pendingPhotoRetries.has(wait.id) ? 'text' : 'error'
    wait.text = '图片已发送，但当前无法完成视觉讲解：' + (errDetail(err) || '请稍后重试。')
    wait.retryVision = pendingPhotoRetries.has(wait.id)
    console.error(err)
  } finally {
    wait.pending = false
    wait.streaming = false
    chatSending.value = false
    scrollToBottom()
  }
}

async function retryExplanation(msg: ChatMsg) {
  if (chatSending.value) return
  const photoRetry = pendingPhotoRetries.get(msg.id)
  if (photoRetry && (msg.retryVision || msg.retryDiagnosis || msg.retrySave)) {
    chatSending.value = true
    msg.pending = true
    try {
      const diagnosisTask = msg.retryDiagnosis
        ? student.reviewPhoto(photoRetry.file, photoRetry.questionId, '', photoRetry.sessionId, false, photoRetry.prompt)
          .then((result) => {
            applyPhotoReviewResult(msg, photoRetry.userImage, result)
            void student.loadSessions(true)
            return result
          })
          .catch((reason: unknown) => {
            markPhotoReviewFailure(msg, reason)
            throw reason
          })
        : Promise.resolve(null)
      const visionTask = msg.retryVision
        ? streamVisionReply(msg, photoRetry.file, photoRetry.visionQuestion)
        : Promise.resolve(null)
      const [diagnosisResult, visionResult] = await Promise.allSettled([diagnosisTask, visionTask])

      let retriedPhotoResult: PhotoReviewResult | null = null
      if (diagnosisResult.status === 'fulfilled' && diagnosisResult.value) {
        retriedPhotoResult = diagnosisResult.value
      }

      if (visionResult.status === 'fulfilled' && visionResult.value) {
        msg.retryVision = false
        photoRetry.assistantText = visionResult.value
      } else if (visionResult.status === 'rejected') {
        msg.retryVision = true
        const partial = msg.text.trim()
        msg.text = partial
          ? `${partial}\n\n视觉讲解中断了，可以再次重试。`
          : '视觉模型暂时无法生成讲解，请重试。'
        console.error(visionResult.reason)
      }

      if (photoRetry.assistantText && !photoRetry.assistantSaved) {
        try {
          await student.appendAgentAssistantMessage(
            photoRetry.sessionId,
            photoRetry.assistantText,
            msg.relatedMistake?.id
          )
          photoRetry.assistantSaved = true
          msg.retrySave = false
          void student.loadSessions(true)
        } catch (saveError) {
          msg.retrySave = true
          console.error(saveError)
        }
      }

      if (retriedPhotoResult?.mode === 'answer' && retriedPhotoResult.capture_id && photoRetry.assistantText) {
        const saveQuestion = /加入|收录|保存|放(?:到|进|入)?|加(?:到|进|入)|记(?:到|进)|收藏/.test(photoRetry.prompt) && /错题本|错题/.test(photoRetry.prompt)
        if (saveQuestion) {
          try {
            await student.savePhotoCapture(retriedPhotoResult.capture_id, photoRetry.assistantText)
            msg.saved = true
            void student.loadSessions(true)
          } catch (saveError) {
            console.error(saveError)
          }
        }
      }

      if (!msg.retryVision && !msg.retryDiagnosis && !msg.retrySave && photoRetry.assistantSaved) {
        pendingPhotoRetries.delete(msg.id)
      }
    } catch (err) {
      msg.text += `\n\n重试失败：${errDetail(err) || '请稍后重试。'}`
      console.error(err)
    } finally {
      msg.pending = false
      msg.streaming = false
      chatSending.value = false
      scrollToBottom()
    }
    return
  }

  if (!msg.retryPrompt) return
  const prompt = msg.retryPrompt
  const safeToolsOnly = msg.retrySafeToolsOnly ?? true
  chatSending.value = true
  msg.pending = true
  try {
    await streamAssistantReply(msg, prompt, false, safeToolsOnly, msg.relatedMistake?.id)
  } catch (err) {
    msg.kind = 'text'
    msg.text = '批改记录已保存，但讲解仍未生成：' + (errDetail(err) || '请稍后重试。')
    msg.retryPrompt = prompt
    msg.retrySafeToolsOnly = safeToolsOnly
    console.error(err)
  } finally {
    msg.pending = false
    chatSending.value = false
    scrollToBottom()
  }
}
async function savePhotoQuestion(msg: ChatMsg) {
  if (!msg.captureId || msg.saved || msg.savingCapture) return
  msg.savingCapture = true
  try {
    await student.savePhotoCapture(msg.captureId, msg.text)
    msg.saved = true
  } catch (err) {
    pushMsg({ side: 'ai', kind: 'error', text: '加入错题本失败：' + (errDetail(err) || '请稍后重试。') })
  } finally {
    msg.savingCapture = false
    scrollToBottom()
  }
}

async function confirmTranscribe(msg: ChatMsg) {
  const steps = msg.steps.map((s) => s.trim()).filter(Boolean)
  if (!steps.length) {
    pushMsg({ side: 'ai', kind: 'error', text: '转写卡片里的步骤是空的，先补上步骤再确认批改。' })
    return
  }
  if (!msg.questionId) {
    pushMsg({ side: 'ai', kind: 'error', text: '请先在转写卡片里选择这道题对应课本里的哪一题。' })
    return
  }
  msg.submitting = true
  try {
    const res = await student.submitMath({ question_id: msg.questionId, steps })
    msg.confirmed = true
    doneQids.value.add(msg.questionId)
    pushMsg({ side: 'ai', kind: 'diagnosis', result: res })
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '批改失败：' + (errDetail(e) || '请稍后重试。') })
    console.error(e)
  } finally {
    msg.submitting = false
    scrollToBottom()
  }
}

// ---------- 初始化 ----------
onMounted(async () => {
  window.addEventListener('keydown', onImagePreviewKeydown)
  try {
    const [list, subs] = await Promise.all([
      student.fetchAssignments(),
      student.fetchMySubmissions().catch(() => [])
    ])
    assignments.value = list
    subs.forEach((s) => doneQids.value.add(s.question_id))
    const details = await Promise.all(list.map((a) => student.fetchAssignmentDetail(a.id)))
    details.forEach((d) => {
      questionsByAssignment.value[d.id] = d.questions
      d.questions.forEach((q) => flatQuestions.value.push({ ...q, assignmentTitle: d.title }))
    })
    // 预选：优先用路由参数（简报/交作业页带过来），否则默认第一份作业的第一道数学题
    const presetAssignment = Number(route.query.assignment_id)
    const presetQuestion = Number(route.query.question_id)
    if (presetAssignment && questionsByAssignment.value[presetAssignment]) {
      assignmentId.value = presetAssignment
      const qs = currentQuestions.value
      questionId.value = qs.some((q) => q.id === presetQuestion)
        ? presetQuestion
        : (qs.find((q) => !doneQids.value.has(q.id))?.id ?? qs[0]?.id ?? '')
    }
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '作业数据加载失败，请确认后端已启动后刷新页面。' })
    console.error(e)
  }
  try {
    const briefing = await student.fetchBriefing()
    // 简报作为第一条 AI 消息
    messages.value.unshift({
      id: ++seq,
      side: 'ai',
      kind: 'briefing',
      text: '',
      url: '',
      briefing,
      questionText: '',
      steps: [],
      questionId: null,
      confirmed: false,
      submitting: false,
      pending: false,
      result: null,
      captureId: null,
      saved: false,
      savingCapture: false,
      relatedMistake: null
    })
  } catch (e) {
    pushMsg({ side: 'ai', kind: 'error', text: '学习简报加载失败，刷新页面可以重试。' })
    console.error(e)
  }
  // 按上次选中的会话读取历史，避免刷新后跳到别的会话。
  await student.loadSessions()
  try {
    const history = student.activeSessionId == null
      ? []
      : await student.fetchSessionMessages(student.activeSessionId)
    history.forEach(restoreHistoryMessage)
  } catch (e) {
    console.error(e)
  }
  // 当前会话定位（v0.6.2）：会话状态归 store 与侧栏共用，loadSessions 首次会自动定位
  // 当前会话（最近更新的一条，与上面 fetchAgentHistory 返回当前会话的口径一致）；
  // appliedViewSeq 对齐当前值，避免把挂载前侧栏的查看请求误当成新切换
  appliedViewSeq = student.sessionView.seq
  loadingInit.value = false
  scrollToBottom()
})
</script>

<style scoped>
.chat-layout { position: relative; display: flex; width: calc(100% - 20px); min-width: 0; min-height: 0; flex-direction: column; height: calc(100dvh - 20px); margin: 10px; overflow: hidden; border: 1px solid var(--border); border-radius: 16px; background: var(--card); box-shadow: 0 2px 8px rgba(31, 49, 77, 0.035); }
.chat-inner { max-width: 1280px; width: 100%; margin: 0 auto; padding: 0 20px; }
.chat-header { flex: 0 0 auto; background: var(--card); border-bottom: 0; padding: 9px 0; }
.chat-title { display: flex; align-items: center; gap: 10px; color: var(--text); }
.chat-title-mark { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 11px; background: var(--primary-50); color: var(--primary); }
.chat-title-copy { display: flex; flex-direction: column; gap: 1px; }
.chat-title-copy strong { font-size: 14px; font-weight: 700; line-height: 1.25; }
.chat-title-copy small { color: var(--text-3); font-size: 11px; font-weight: 400; }
.chat-status { margin-left: auto; display: inline-flex; align-items: center; gap: 7px; color: var(--text-3); font-size: 12px; font-weight: 500; }
.chat-status i { width: 7px; height: 7px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 3px var(--green-bg); }
.photo-capture-action { margin-top: 10px; }
.photo-capture-action > span { color: var(--green); font-size: 12px; font-weight: 600; }
.ai-message-text { display: flex; align-items: flex-start; gap: 8px; line-height: 1.75; }
.ai-message-markdown { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.ai-message-streaming { white-space: pre-wrap; }
.ai-message-markdown :deep(:first-child) { margin-top: 0; }
.ai-message-markdown :deep(:last-child) { margin-bottom: 0; }
.ai-message-markdown :deep(p) { margin: 0 0 0.75em; white-space: pre-wrap; }
.ai-message-markdown :deep(h1), .ai-message-markdown :deep(h2), .ai-message-markdown :deep(h3), .ai-message-markdown :deep(h4) { margin: 0.9em 0 0.45em; color: var(--text); line-height: 1.4; }
.ai-message-markdown :deep(ul), .ai-message-markdown :deep(ol) { margin: 0.35em 0 0.8em; padding-left: 1.6em; }
.ai-message-markdown :deep(li + li) { margin-top: 0.2em; }
.ai-message-markdown :deep(hr) { margin: 1em 0; border: 0; border-top: 1px solid var(--border); }
.ai-message-markdown :deep(blockquote) { margin: 0.6em 0; border-left: 3px solid var(--border); padding-left: 0.8em; color: var(--text-2); }
.ai-message-markdown :deep(pre) { overflow-x: auto; margin: 0.6em 0; border-radius: 8px; background: var(--surface-2, #f5f7fa); padding: 10px 12px; }
.ai-message-markdown :deep(code) { border-radius: 4px; background: var(--surface-2, #f5f7fa); padding: 0.08em 0.25em; font-size: 0.92em; }
.ai-message-markdown :deep(pre code) { background: transparent; padding: 0; }
.ai-message-markdown :deep(a) { color: var(--primary); text-decoration: underline; }
.photo-mistake-sync { display: flex; align-items: flex-start; gap: 7px; margin-top: 10px; border-radius: 8px; background: var(--green-bg); color: var(--green); padding: 9px 11px; font-size: 12px; line-height: 1.5; }
.photo-mistake-sync.is-pending { background: var(--amber-bg); color: #92400E; }
.photo-mistake-sync.is-deferred { background: var(--amber-bg); color: #92400E; }
.photo-mistake-sync.is-error { background: #FEF2F2; color: #B91C1C; }
.photo-mistake-sync.is-empty { background: var(--surface-2, #f5f7fa); color: var(--text-2); }
.photo-mistake-sync > span { display: flex; flex: 1; flex-direction: column; }
.photo-mistake-sync small { margin-top: 2px; font-size: 11px; }
.photo-mistake-sync a { flex: 0 0 auto; color: var(--primary); font-weight: 650; text-decoration: none; }
.photo-mistake-sync a:hover { text-decoration: underline; }
.related-mistake-link { display: inline-flex; align-items: center; gap: 3px; margin-top: 9px; padding: 0; border: 0; background: none; color: var(--primary); font: inherit; font-size: 13px; font-weight: 650; cursor: pointer; }
.related-mistake-link:hover { text-decoration: underline; }

.chat-content-shell { display: flex; min-height: 0; flex: 1 1 auto; flex-direction: column; }
.chat-content-shell.welcome-mode { justify-content: center; gap: 18px; overflow-y: auto; padding: 28px 24px 168px; }
/* 底部留白给悬浮输入卡让位（v0.8.1）：最后的消息不被卡片遮住 */
.chat-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 20px 0 168px; background: var(--card); }
.chat-body-welcome { flex: 0 0 auto; overflow: visible; padding: 0; }
.welcome-mode .chat-inner { max-width: 780px; padding: 0; }
.welcome-home { padding: 0 2px; }
.welcome-kicker { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; color: var(--text-2); font-size: 12px; font-weight: 600; }
.welcome-kicker::before { width: 18px; height: 2px; border-radius: 2px; background: var(--primary); content: ''; }
.welcome-home h1 { color: var(--text); font-size: clamp(29px, 2.8vw, 37px); font-weight: 650; line-height: 1.3; letter-spacing: -0.025em; }
.welcome-description { margin-top: 8px; color: var(--text-2); font-size: 14px; }
.welcome-briefing { margin-top: 22px; padding: 16px 18px; border: 1px solid var(--border); border-radius: 14px; background: rgba(255, 255, 255, 0.88); }
.welcome-briefing-heading { display: flex; align-items: center; gap: 9px; color: var(--text); }
.welcome-briefing-heading > div { display: flex; flex-direction: column; gap: 1px; }
.welcome-briefing-heading strong { font-size: 13px; font-weight: 650; }
.welcome-briefing-heading small { color: var(--text-3); font-size: 11px; }
.welcome-briefing-icon { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 9px; background: var(--primary-50); color: var(--text-2); }
.welcome-briefing-book { display: inline-flex; align-items: center; gap: 2px; margin-left: auto; color: var(--primary); font-size: 12px; font-weight: 600; white-space: nowrap; }
/* 欢迎屏简报卡组（v0.9.0）：复用对话内简报卡的大数字+色块规格，整卡可点跳转 */
.welcome-brief-grid { margin-top: 14px; }
.brief-clickable { cursor: pointer; transition: box-shadow 0.2s ease, transform 0.2s ease; }
.brief-clickable:hover { box-shadow: var(--shadow-md); transform: translateY(-2px); }
.brief-card-more { display: inline-flex; align-items: center; gap: 2px; margin-top: 10px; color: var(--primary); font-size: 12.5px; font-weight: 600; }
.brief-weakstat { background: var(--amber-bg); }
.brief-weakstat .brief-big { color: var(--amber); }
.brief-weak-list { display: flex; flex-direction: column; gap: 4px; }
.brief-weak-line { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.welcome-briefing-feedback { margin: 11px 0 0; border-top: 1px solid var(--border); padding-top: 9px; color: var(--text-2); font-size: 11.5px; }
/* 待老师审核状态盒（v0.9.0）：对话诊断卡与详情共用语义 */
.review-pending-box { display: flex; gap: 11px; align-items: flex-start; background: var(--amber-bg); border: 1px solid #FDE68A; border-radius: 10px; padding: 13px 15px; }
.review-pending-icon { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0; background: #fff; color: var(--amber); display: flex; align-items: center; justify-content: center; }
.review-pending-title { font-size: 14.5px; font-weight: 700; color: #92400E; }
.review-pending-sub { font-size: 13px; color: #92400E; opacity: 0.85; margin-top: 2px; }
.welcome-briefing-done { display: flex; align-items: flex-start; gap: 10px; margin-top: 13px; border-radius: 10px; background: var(--green-bg); padding: 12px 13px; }
.welcome-done-mark { display: grid; width: 27px; height: 27px; flex: 0 0 27px; place-items: center; border-radius: 50%; background: var(--green); color: #fff; }
.welcome-briefing-done strong { color: #065F46; font-size: 13px; font-weight: 650; }
.welcome-briefing-done p { margin-top: 3px; color: var(--text-2); font-size: 11.5px; }

/* 建议气泡（v0.6.0）：只挂最新一轮回复，淡入上浮 stagger */
.suggest-row { display: flex; gap: 8px; flex-wrap: wrap; margin: -4px 0 16px 40px; }
.suggest-chip {
  border: 1px solid var(--blue-bg);
  background: linear-gradient(135deg, #FFFFFF 0%, var(--primary-50) 100%);
  color: var(--primary);
  border-radius: 999px; padding: 6px 13px; font-size: 13px; font-weight: 600;
  cursor: pointer; font-family: var(--font);
  animation: suggest-in 0.35s ease both;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.suggest-chip:hover { transform: translateY(-1px); box-shadow: var(--shadow); }
@keyframes suggest-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.brief-item-sub { display: block; font-size: 12.5px; color: var(--text-2); margin-top: 2px; }
.msg-row { display: flex; gap: 10px; margin-bottom: 16px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar {
  width: 30px; height: 30px; border-radius: 50%;
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px;
}
.bubble { border-radius: 14px; padding: 11px 16px; font-size: 14.5px; max-width: 78%; white-space: pre-wrap; word-break: break-word; }
.ai-bubble { background: var(--card); border: 1px solid var(--border); box-shadow: var(--shadow); display: inline-flex; flex-direction: column; align-items: flex-start; gap: 0; }
.error-bubble { background: var(--red-bg); color: #991B1B; display: inline-flex; align-items: center; gap: 8px; }
.user-bubble { background: var(--primary); color: #fff; }
.user-image-card { display: grid; width: fit-content; max-width: min(210px, 72vw); gap: 8px; padding: 8px; border: 1px solid var(--border); border-radius: 16px 16px 4px 16px; background: #F3F4F0; }
.user-image-prompt { margin: 0 2px 2px; color: var(--text); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.user-image-trigger { display: flex; width: fit-content; max-width: 100%; justify-content: center; margin: 0 auto; padding: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 10px; background: #fff; cursor: zoom-in; }
.user-image img { display: block; width: auto; height: auto; max-width: 190px; max-height: 135px; object-fit: contain; }
.user-image-caption { display: block; max-width: 100%; padding: 0 2px; border: 0; background: transparent; color: var(--text-2); font: inherit; font-size: 12px; line-height: 1.4; text-align: left; overflow-wrap: anywhere; cursor: zoom-in; }

.ai-card {
  background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  box-shadow: var(--shadow); padding: 16px 18px; width: min(900px, 100%);
}
.ai-card-title { font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }

/* 简报卡片区（v0.2.1 卡片化；v0.4.0 放宽卡宽，统计卡真正横向并排） */
.briefing-card { width: min(1040px, 100%); }
.brief-hello { font-size: 14.5px; margin-bottom: 12px; }
.brief-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.brief-stat-card { border-radius: 12px; padding: 14px 16px; border: 1px solid var(--border); }
.brief-assign { background: var(--primary-50); }
.brief-corr { background: var(--amber-bg); }
.brief-stat-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.brief-big { font-size: 30px; font-weight: 800; line-height: 1.1; color: var(--primary); }
.brief-corr .brief-big { color: var(--amber); }
.brief-stat-label { font-size: 13.5px; font-weight: 600; color: var(--text-2); }
.brief-one-line { font-size: 13px; color: var(--text-2); margin-bottom: 10px; }
.brief-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px solid rgba(29, 78, 216, 0.12); }
.brief-item-main { font-size: 14px; }
.brief-label { font-size: 13px; font-weight: 600; color: var(--text-2); margin-bottom: 8px; }
.brief-weak { margin-top: 14px; }
.brief-weak-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
.brief-weak-card {
  background: var(--amber-bg); border-radius: 10px; padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.brief-weak-name { font-size: 14px; font-weight: 700; color: #92400E; }
.brief-weak-meta { font-size: 12px; color: #92400E; opacity: 0.85; }
.brief-recent { margin-top: 14px; font-size: 13px; color: var(--text-2); border-top: 1px solid var(--border); padding-top: 10px; }
.brief-done { display: flex; gap: 12px; background: var(--green-bg); border-radius: 12px; padding: 14px 16px; }
.brief-done-icon {
  width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0;
  background: var(--green); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.brief-done-title { font-size: 15.5px; font-weight: 700; color: #065F46; margin-bottom: 2px; }
.brief-done-line { font-size: 13.5px; color: #065F46; }

/* 简报摘要条 + 展开区（本轮小改）：条与展开区都是 .chat-inner 的直接子级
   （不套在 .msg-row 里），摘要条才能在整个消息流滚动中吸顶；
   展开区用 grid-template-rows 0fr→1fr + 透明度做平滑推开/收起 */
.brief-bar {
  position: sticky; top: 10px; z-index: 5;
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 14px; padding: 7px 8px 7px 12px;
  border: 1px solid var(--border); border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  -webkit-backdrop-filter: blur(10px) saturate(1.3);
  backdrop-filter: blur(10px) saturate(1.3);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.07);
  font-size: 12.5px; color: var(--text-2);
}
.brief-bar-icon { display: grid; width: 22px; height: 22px; flex-shrink: 0; place-items: center; border-radius: 50%; background: var(--primary-50); color: var(--primary); }
.brief-bar-label { flex-shrink: 0; font-weight: 700; color: var(--text); white-space: nowrap; }
.brief-bar-items { display: flex; min-width: 0; align-items: center; gap: 6px; overflow: hidden; white-space: nowrap; }
.brief-bar-item { overflow: hidden; text-overflow: ellipsis; }
.brief-bar-item b { color: var(--primary); font-weight: 800; }
.brief-bar-item.corr b, .brief-bar-item.weak b { color: var(--amber); }
.brief-bar-sep { flex-shrink: 0; color: var(--text-3); }
.brief-bar-done { display: inline-flex; min-width: 0; align-items: center; gap: 5px; overflow: hidden; color: #065F46; font-weight: 600; white-space: nowrap; text-overflow: ellipsis; }
.brief-bar-toggle {
  display: inline-flex; flex-shrink: 0; align-items: center; gap: 3px;
  margin-left: auto; padding: 4px 10px;
  border: 1px solid var(--border); border-radius: 999px;
  background: #fff; color: var(--primary);
  font-family: var(--font); font-size: 12px; font-weight: 600; cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}
.brief-bar-toggle:hover { background: var(--primary-50); border-color: rgba(29, 78, 216, 0.35); }
.brief-bar-chevron { transition: transform 0.3s ease; }
.brief-bar-chevron.open { transform: rotate(180deg); }
.brief-expand { display: grid; grid-template-rows: 0fr; visibility: hidden; opacity: 0; transition: grid-template-rows 0.38s ease, opacity 0.3s ease, visibility 0s linear 0.38s; }
.brief-expand.open { grid-template-rows: 1fr; visibility: visible; opacity: 1; transition: grid-template-rows 0.38s ease, opacity 0.3s ease; }
.brief-expand-inner { min-height: 0; overflow: hidden; padding-left: 40px; }
.brief-expand-inner .briefing-card { width: 100%; margin-bottom: 16px; }
@media (prefers-reduced-motion: reduce) {
  .brief-expand, .brief-bar-chevron { transition: none; }
}
@media (max-width: 620px) {
  .brief-bar { top: 8px; gap: 6px; padding-left: 9px; font-size: 12px; }
  .brief-bar-label { display: none; }
  .brief-expand-inner { padding-left: 0; }
}

.mini-label { display: block; font-size: 13px; color: var(--text-2); margin: 12px 0 6px; }
.transcribe-step { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.transcribe-step .step-idx { min-width: 20px; text-align: right; color: var(--text-3); font-size: 13px; }

.diag-step {
  display: flex; gap: 10px;
  border: 1px solid var(--border); border-left: 4px solid var(--border);
  border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; background: #fff;
}
.diag-step.first-error { border-left-color: var(--red); background: #FFFBFB; }
.diag-step.correct { border-left-color: var(--green); }
.diag-icon { width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; background: var(--gray-bg); color: var(--gray); }
.diag-icon.ok { background: var(--green-bg); color: var(--green); }
.diag-icon.error { background: var(--red-bg); color: var(--red); }
.diag-icon.unparseable { background: var(--amber-bg); color: var(--amber); }
.diag-step-main { flex: 1; min-width: 0; }
.diag-step .step-title { font-weight: 600; font-size: 13px; color: var(--text-3); margin-bottom: 2px; }
.diag-step.first-error .step-title { color: #991B1B; }
.diag-step.correct .step-title { color: #065F46; }
.error-item { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
.encourage { margin-top: 8px; font-size: 14px; }
.detail { margin-top: 6px; font-size: 14px; color: var(--text-2); }
.ok-line { margin-top: 10px; font-size: 14.5px; color: #065F46; display: flex; align-items: center; gap: 6px; }
.followup-box {
  display: flex; gap: 9px; align-items: flex-start;
  background: var(--primary-50); border: 1px solid var(--blue-bg); border-radius: 10px;
  padding: 11px 14px; margin-top: 14px; font-size: 14px;
}
.followup-icon {
  width: 26px; height: 26px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary); color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.followup-box p { padding-top: 3px; }

/* 悬浮输入卡（v0.6.2 版式，v0.8.1 恢复）：毛玻璃卡悬浮在内容区底部，滚动内容从卡下透过去；
   输入框无边框融入卡内，拍照=白底描边圆钮、发送=主色实心圆钮，聚焦时整卡带主色光晕 */
.chat-composer { position: absolute; left: 0; right: 0; bottom: 0; z-index: 6; background: transparent; padding: 10px 0 14px; }
.chat-composer-welcome { background: transparent; }
.composer-panel {
  border: 1px solid var(--border); border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
  -webkit-backdrop-filter: blur(14px) saturate(1.4);
  backdrop-filter: blur(14px) saturate(1.4);
  padding: 13px 15px 11px;
  box-shadow: 0 14px 36px rgba(15, 23, 42, 0.13), 0 2px 8px rgba(15, 23, 42, 0.06);
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
.image-lightbox { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 24px; background: rgba(15, 23, 42, 0.82); cursor: zoom-out; }
.image-lightbox > img { display: block; max-width: min(92vw, 1200px); max-height: 90vh; object-fit: contain; border-radius: 12px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4); cursor: default; }
.image-lightbox-close { position: absolute; top: max(16px, env(safe-area-inset-top)); right: max(16px, env(safe-area-inset-right)); display: grid; width: 42px; height: 42px; place-items: center; border: 1px solid rgba(255, 255, 255, 0.3); border-radius: 50%; background: rgba(255, 255, 255, 0.95); color: #1f2937; cursor: pointer; }
.chat-text-input { display: block; width: 100%; min-width: 0; min-height: 40px; max-height: 150px; resize: none; padding: 7px 8px; border: 0; border-radius: 10px; outline: 0; box-shadow: none; font: inherit; font-size: 15px; line-height: 1.65; }
.chat-text-input:focus { border: 0; outline: 0; box-shadow: none; }
.chat-text-input-welcome { min-height: 54px; font-size: 16px; }
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
.chat-composer-welcome .chat-inner { max-width: 780px; padding: 0; }
.spin { animation: chat-spin 1s linear infinite; }
@keyframes chat-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .suggest-chip { animation: none; transition: none; }
  .composer-panel, .send-btn, .composer-photo-btn { transition: none; }
  .send-btn:hover:not(:disabled) { transform: none; }
}

@media (max-width: 960px) {
  .chat-layout { height: calc(100dvh - 72px); }
  .chat-status { display: none; }
  .user-image-card { max-width: min(210px, 72vw); }
  .user-image img { max-width: 190px; max-height: 125px; }
  .bubble { max-width: 88%; }
  .chat-content-shell.welcome-mode { gap: 16px; padding: 20px 18px 150px; }
  .chat-composer-welcome .chat-inner { padding: 0; }
  .composer-panel { padding: 10px 11px; }
}

@media (max-width: 620px) {
  .chat-header { padding: 7px 0; }
  .chat-inner { padding-right: 14px; padding-left: 14px; }
  .chat-title-mark { width: 31px; height: 31px; }
  .chat-title-copy small { font-size: 10px; }
  .welcome-kicker { margin-bottom: 10px; }
  .welcome-home h1 { font-size: clamp(27px, 7.5vw, 34px); }
  .welcome-description { max-width: 330px; font-size: 13px; }
  .welcome-briefing { margin-top: 17px; padding: 12px; }
  .composer-bottom-row { gap: 6px; }
  .composer-tools { gap: 5px; }
  .composer-context { max-width: 38vw; }
}
</style>
