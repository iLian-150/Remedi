<!-- 学生端：交作业（v0.2.1 拍照为主；v0.3.0 拍照批改原地完成；v0.6.0 一键直达）
     v0.9.0：作业切换改成页面顶部一条独立 sticky 切换条（下拉选作业，原地切换，
     与下方题目列表视觉分开，不再混在题目卡里）；整份作业低于 60 分才进入老师审核。
     v0.9.2 两项逻辑纠正：
     ① 作答方式按作业模式分流——线上作业（mode=online）恢复「在线作答」：
        每道题卡内是文本编辑器（一行一步），提交走 3.3 文本提交接口，与拍照
        完全同链（先 AI 诊断产出步骤诊断与错因，再建 pending 审核行）；
        线下练习册（mode=offline）保持拍照批改。草稿按题目存 localStorage。
     ② 拍照批改点按直达图库：行内按钮点击当下就调 PhotoGradeFlow.openPicker()
        打开系统图库/文件选择，不再先展开一层中间面板；取消选择不留空面板。
     入口：从作业列表进入 /student/submit?assignment_id=；直接访问时用切换条选择。
     契约：3.1 作业列表 / 3.2 作业详情 / 3.3 文本提交（在线作答）/ 3.4 我的提交记录 -->
<template>
  <div class="page">
    <input ref="photoPickerRef" type="file" accept="image/*" hidden @change="onPhotoPickerChange" />
    <div class="page-head">
      <h2>交作业</h2>
      <p class="page-sub">{{ headSub }}</p>
    </div>

    <div v-if="error" class="error-msg">{{ error }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <template v-else>
      <!-- 作业切换条（v0.9.0）：钉在页面顶部，与题目列表分开 -->
      <div class="card switch-bar">
        <span class="switch-label">
          <AppIcon name="clipboard" :size="16" /> 正在交的作业
        </span>
        <!-- v0.13.10：换成自制下拉面板——原生 select 的展开列表是操作系统样式、
             改不动、与全站设计对不齐；面板语言与发布页时间面板保持一致。
             过滤口径不变（v0.13.9）：只列没交完的作业，正在看的已交完作业
             只留一个禁用项标明状态 -->
        <div class="switch-select-wrap" ref="switchWrapRef">
          <button type="button" class="switch-select" :aria-expanded="switchOpen" aria-haspopup="listbox" @click="switchOpen = !switchOpen">
            <span class="switch-select-text">{{ switchLabel }}</span>
            <AppIcon name="chevron-down" :size="16" class="switch-chevron" :class="{ open: switchOpen }" />
          </button>
          <div v-if="switchOpen" class="switch-menu" role="listbox">
            <button v-if="currentFullySubmitted" type="button" class="switch-option" disabled>
              <span class="switch-option-main">
                <span class="switch-option-title">{{ currentAssignment?.title }}</span>
                <span class="switch-option-meta">已全部提交</span>
              </span>
            </button>
            <button
              v-for="a in switchableAssignments" :key="a.id" type="button" class="switch-option"
              :class="{ active: a.id === assignmentId }" role="option" :aria-selected="a.id === assignmentId"
              @click="chooseAssignment(a.id)"
            >
              <span class="switch-option-main">
                <span class="switch-option-title">{{ a.title }}</span>
                <span class="switch-option-meta">{{ a.question_count }} 题<template v-if="a.submitted_count"> · 已交 {{ a.submitted_count }} 题</template> · {{ a.photo_required ? '拍照提交' : '在线答题' }}</span>
              </span>
              <AppIcon v-if="a.id === assignmentId" name="check" :size="15" class="switch-option-check" />
            </button>
            <p v-if="!switchableAssignments.length && !currentFullySubmitted" class="switch-menu-empty">能交的作业都交完啦，去作业列表看看成绩吧。</p>
          </div>
        </div>
        <router-link to="/student/assignments" class="switch-all">全部作业 <AppIcon name="chevron-right" :size="13" /></router-link>
      </div>

      <!-- 当前作业信息（v0.13.1 精简）：只留标题、老师写的说明、截止时间与必要的作答提示；
           说明没填就不显示这一行（不再占位「暂无说明」），截止时间两种模式都显示 -->
      <div v-if="currentDetail" class="card assign-info">
        <p><strong>{{ currentDetail.title }}</strong></p>
        <p v-if="currentDetail.description" class="kp">{{ currentDetail.description }}</p>
        <p v-if="currentDetail.deadline" class="kp deadline-line">
          截止 {{ currentDetail.deadline.replace('T', ' ').slice(0, 16) }}
        </p>
        <p v-if="currentDetail.mode === 'offline'" class="kp" style="margin-top: 4px">
          <template v-if="currentDetail.workbook_title">{{ currentDetail.workbook_title }}</template>
          <template v-if="currentDetail.page_range"> · {{ currentDetail.page_range }}</template>
          —— 练习册完成后逐题上传作答照片。
        </p>
      </div>

      <!-- 线上做题板（v0.13.1）：一次只看一道题——题干放大、不再堆知识点等小字；
           数学符号栏插入的符号都是后端解析器认得的（× ÷ ² ³ √ π 等）；
           底部左「答题卡」弹层跳题、右下角上一题/下一题翻页 -->
      <div v-if="onlineQuestions.length" class="card board-card">
        <template v-if="currentQ">
          <div class="board-head">
            <span class="board-progress tnum">第 {{ currentIdx + 1 }} / {{ onlineQuestions.length }} 题</span>
            <span class="board-status">
              <span v-if="gradingJobStatus === 'queued'" class="badge badge-amber">待批改</span>
              <span v-else-if="gradingJobStatus === 'processing'" class="badge badge-blue">批改中</span>
              <span v-else-if="noteKind(currentQ) === 'deferred'" class="badge badge-amber">待统一批改</span>
              <span v-else-if="pendingQids.has(currentQ.id)" class="badge badge-amber">待老师审核</span>
              <span v-else-if="doneQids.has(currentQ.id)" class="badge badge-green">已完成</span>
              <span v-else-if="answeredQids.has(currentQ.id)" class="badge badge-amber">已作答</span>
              <span v-else class="badge badge-gray">未完成</span>
              <span v-if="gradingJobStatus === 'completed' && scoreByQid[currentQ.id]" class="badge badge-green tnum">得分 {{ fmtScore(scoreByQid[currentQ.id].score) }} / {{ fmtScore(scoreByQid[currentQ.id].max) }} 分</span>
            </span>
          </div>
          <!-- 大题共享材料（v0.13.1）：本题属于大题时，题干上方先给材料 -->
          <div v-if="groupStemOf(currentQ)" class="board-group-stem">
            <span class="board-group-tag">大题材料</span>
            <div class="group-stem-content" :class="{ 'has-diagram': groupDiagramOf(currentQ) }">
              <p>{{ groupStemOf(currentQ) }}</p>
              <FigureRenderer v-if="groupDiagramOf(currentQ)" :figure="groupDiagramOf(currentQ)!" />
              <span v-else-if="groupFigurePending(currentQ)" class="hint" role="status">图形生成中，将自动显示</span>
            </div>
          </div>
          <p class="board-stem">{{ currentQ.stem }}</p>

          <!-- 本题已提交且没重开编辑器：显示状态卡。
               v0.13.1 起提交后锁定，不能直接再交；老师开了「允许修改」时，
               改题入口统一在页面底部的「修改作业」区 -->
          <template v-if="batchLocked || ((noteKind(currentQ) || answeredQids.has(currentQ.id)) && !editorOpen[currentQ.id] && !(isShowingImage(currentQ.id) && gradingJobStatus !== 'completed'))">
            <div v-if="gradingJobStatus === 'queued' || gradingJobStatus === 'processing'" class="review-pending-box board-note">
              <span class="review-pending-icon"><AppIcon :name="gradingJobStatus === 'processing' ? 'spinner' : 'history'" :size="17" /></span>
              <div>
                <p class="review-pending-title">{{ gradingJobStatus === 'processing' ? '整份作业批改中' : '整份作业待批改' }}</p>
                <p class="review-pending-sub">已完成 {{ gradingJobProgress }} / {{ gradingJobTotal }} 题。批改结果生成后会显示在这里。</p>
              </div>
            </div>
            <div v-else-if="answeredQids.has(currentQ.id) && gradingJobStatus !== 'completed'" class="review-pending-box board-note">
              <span class="review-pending-icon"><AppIcon name="check" :size="17" /></span>
              <div>
                <p class="review-pending-title">本题作答已保存</p>
                <p class="review-pending-sub">{{ allAnswersStaged ? '全部题目已完成，请点击提交作业。' : '完成剩余题目后，点击提交作业统一批改。' }}</p>
              </div>
              <button class="btn small secondary" :disabled="batchLocked" @click="editorOpen[currentQ.id] = true">修改答案</button>
            </div>
            <div v-else-if="noteKind(currentQ) === 'deferred'" class="review-pending-box board-note">
              <span class="review-pending-icon"><AppIcon name="history" :size="17" /></span>
              <div>
                <p class="review-pending-title">已提交，截止后统一批改</p>
                <p class="review-pending-sub">这份作业老师开启了「截止后统一批改」：截止前想改这道题，去页面底部的「修改作业」里改，改完以最后一次提交为准。</p>
              </div>
            </div>
            <div v-else-if="noteKind(currentQ) === 'pending'" class="review-pending-box board-note">
              <span class="review-pending-icon"><AppIcon name="history" :size="17" /></span>
              <div>
                <p class="review-pending-title">已提交，诊断和订正入口已同步生成</p>
                <p class="review-pending-sub">这份作业总分低于 60 分，已进入教师审核。系统评分已显示，错题和订正任务也已同步；你可以先继续订正。每道题只能提交一次。<template v-if="currentDetail?.allow_revision">如需修改，去页面底部的「修改作业」。</template></p>
              </div>
              <router-link class="btn small secondary" to="/student/corrections">现在去订正</router-link>
            </div>
            <p v-else class="submit-ok-line board-note">
              <AppIcon name="check" :size="15" /> 已提交，批改结果已生成，去学习报告或错题本看看吧。
            </p>
          </template>

          <!-- 作答编辑器：一行一步 + 数学符号栏，草稿自动保存在本机 -->
          <div v-else class="answer-editor board-editor">
            <div v-if="currentQ.subject === 'math' && !handwritingOpen[currentQ.id]" class="symbol-bar" role="group" aria-label="数学符号">
              <button
                v-for="s in SYMBOLS"
                :key="s.label"
                type="button"
                class="symbol-btn"
                :title="`插入 ${s.label}`"
                @click="insertSymbol(s)"
              >{{ s.label }}</button>
            </div>
            <div class="answer-mode-row">
              <button
                type="button"
                class="btn secondary small inline-icon"
                :disabled="submittingMap[currentQ.id] || batchLocked || batchSubmitting"
                @click="pickPhoto(currentQ.id)"
              >
                <AppIcon name="image" :size="15" /> {{ isShowingImage(currentQ.id) ? '重新上传图片' : '上传手写图片' }}
              </button>
              <button
                type="button"
                class="btn small inline-icon"
                :class="handwritingOpen[currentQ.id] ? '' : 'secondary'"
                :aria-expanded="!!handwritingOpen[currentQ.id]"
                :disabled="submittingMap[currentQ.id] || batchLocked || batchSubmitting"
                @click="toggleHandwriting(currentQ.id)"
              >
                <AppIcon name="edit" :size="15" />
                {{ handwritingOpen[currentQ.id] ? '收起手写板' : '电子手写' }}
              </button>
            </div>
            <HandwritingPad
              v-if="handwritingOpen[currentQ.id]"
              :key="currentQ.id"
              :ref="(el) => setHandwritingRef(currentQ.id, el)"
              :storage-key="handwritingDraftKey(currentQ.id)"
              :disabled="submittingMap[currentQ.id] || batchLocked || batchSubmitting"
              @submit="submitHandwriting(currentQ, $event)"
            />
            <template v-if="!handwritingOpen[currentQ.id]">
              <div v-if="isShowingImage(currentQ.id)" class="editor-wrap image-answer-wrap">
                <img v-if="photoPreviews[currentQ.id]" :src="photoPreviews[currentQ.id]" alt="本题作答图片" class="answer-image" />
                <div v-else-if="photoLoadErrors[currentQ.id]" class="image-load-error" role="alert">
                  <span>{{ photoLoadErrors[currentQ.id] }}</span>
                  <button type="button" class="btn small secondary" @click="loadOnlinePhoto(Number(assignmentId), currentQ.id)">重新加载图片</button>
                </div>
                <span v-else class="hint" role="status">作答图片加载中…</span>
              </div>
              <div v-else class="editor-wrap">
                <div class="editor-gutter" aria-hidden="true">
                  <div class="editor-gutter-inner" :style="{ transform: `translateY(${-(gutterScroll[currentQ.id] ?? 0)}px)` }">
                    <span v-for="n in currentDraftMetrics.lineCount" :key="n" class="tnum">{{ n }}</span>
                  </div>
                </div>
                <textarea
                  ref="boardTextarea"
                  :value="drafts[currentQ.id] ?? ''"
                  class="answer-textarea"
                  :disabled="batchLocked || batchSubmitting"
                  spellcheck="false"
                  :placeholder="currentQ.subject === 'math' ? '每行写一步解题过程，最后一行写最终答案。' : '在这里输入你的作答内容'"
                  @input="onDraftInput(currentQ.id, $event)"
                  @scroll="onEditorScroll(currentQ.id, $event)"
                />
              </div>
              <template v-if="isShowingImage(currentQ.id)">
                <p v-if="submittingMap[currentQ.id]" class="editor-meta" role="status">正在保存作答图片…</p>
                <p v-else-if="answeredQids.has(currentQ.id) && !photoPendingFiles[currentQ.id]" class="editor-meta" role="status">作答图片已保存</p>
                <div class="toolbar" style="margin: 10px 0 0">
                  <button v-if="photoPendingFiles[currentQ.id] && answerErrors[currentQ.id]" type="button" class="btn small secondary" :disabled="submittingMap[currentQ.id]" @click="retryOnlinePhoto(currentQ.id)">重试保存</button>
                  <button type="button" class="btn small secondary" :disabled="submittingMap[currentQ.id] || batchLocked || batchSubmitting" @click="useTextAnswer(currentQ.id)">改为文字作答</button>
                </div>
              </template>
              <template v-else>
                <div class="editor-meta">
                  <span class="tnum">{{ currentQ.subject === 'math' ? `${currentDraftMetrics.stepCount} / 20 步` : `已输入 ${currentDraftMetrics.stepCount} 行` }}</span>
                  <span v-if="currentQ.subject === 'math' && currentDraftMetrics.stepCount > 20" class="editor-warn">步骤最多 20 步，请把几步合并一下再提交。</span>
                  <span v-else-if="(drafts[currentQ.id] ?? '').trim()" class="editor-saved">草稿已自动保存在这台设备上</span>
                </div>
                <p v-if="photoTextMode[currentQ.id] && imageQuestionIds.has(currentQ.id)" class="hint">原图片仍已保存，保存文字后将替换。</p>
                <div class="toolbar" style="margin: 10px 0 0">
                  <button
                    class="btn"
                    :disabled="submittingMap[currentQ.id] || batchLocked || batchSubmitting || currentDraftMetrics.stepCount === 0 || (currentQ.subject === 'math' && currentDraftMetrics.stepCount > 20)"
                    @click="submitAnswer(currentQ)"
                  >
                    {{ submittingMap[currentQ.id] ? '保存中…' : '保存本题答案' }}
                  </button>
                  <button class="btn secondary" :disabled="submittingMap[currentQ.id] || batchLocked || batchSubmitting" @click="clearDraft(currentQ.id)">清空重写</button>
                  <button v-if="photoTextMode[currentQ.id] && imageQuestionIds.has(currentQ.id)" type="button" class="btn secondary" :disabled="submittingMap[currentQ.id]" @click="restorePhotoAnswer(currentQ.id)">保留已保存图片</button>
                </div>
              </template>
            </template>
            <div v-if="answerErrors[currentQ.id]" class="error-msg" style="margin-top: 10px">{{ answerErrors[currentQ.id] }}</div>
          </div>

          <button v-if="relatedByQid[currentQ.id]" type="button" class="related-mistake-entry" @click="openRelatedMistake(relatedByQid[currentQ.id]!)">
            回看以前错过的同类题 <AppIcon name="chevron-right" :size="14" />
          </button>

          <!-- 底部导航：左答题卡、右翻页（右下角） -->
          <div class="board-nav">
            <button type="button" class="btn secondary inline-icon" @click="cardOpen = !cardOpen">
              <AppIcon name="clipboard" :size="15" /> 答题卡
            </button>
            <div class="board-nav-right">
              <button type="button" class="btn secondary" :disabled="currentIdx === 0" @click="gotoQuestion(currentIdx - 1)">上一题</button>
              <button v-if="currentIdx < onlineQuestions.length - 1" type="button" class="btn" @click="gotoQuestion(currentIdx + 1)">下一题</button>
              <button v-if="allAnswersStaged && gradingJobStatus === 'draft'" type="button" class="btn" :disabled="!canSubmitAssignment" @click="queueWholeAssignment">{{ batchSubmitting ? '提交中…' : '提交作业' }}</button>
            </div>
            <div v-if="cardOpen" class="answer-card-pop">
              <div class="answer-card-grid">
                <button
                  v-for="(q, i) in onlineQuestions"
                  :key="q.id"
                  type="button"
                  class="answer-cell tnum"
                  :class="{ current: i === currentIdx, done: doneQids.has(q.id), pending: pendingQids.has(q.id) || deferredQids.has(q.id) }"
                  @click="gotoQuestion(i)"
                >{{ i + 1 }}</button>
              </div>
              <p class="answer-card-legend">
                <span class="dot done"></span>已完成
                <span class="dot pending"></span>待审核
                <span class="dot todo"></span>未完成
              </p>
            </div>
          </div>
        </template>
      </div>

      <!-- 线下题目列表（v0.13.1 精简）：题干放大，只留状态与得分，不再挂知识点小字 -->
      <div v-if="photoQuestions.length" class="card">
        <h3>题目列表</h3>
        <template v-for="(q, qi) in photoQuestions" :key="q.id">
          <!-- 大题共享材料（v0.13.1）：一组小题上方只展示一次 -->
          <div v-if="showGroupBanner(q, qi, photoQuestions)" class="group-stem-banner">
            <span class="board-group-tag">大题材料</span>
            <div class="group-stem-content" :class="{ 'has-diagram': groupDiagramOf(q) }">
              <p>{{ groupStemOf(q) }}</p>
              <FigureRenderer v-if="groupDiagramOf(q)" :figure="groupDiagramOf(q)!" />
              <span v-else-if="groupFigurePending(q)" class="hint" role="status">图形生成中，将自动显示</span>
            </div>
          </div>
          <div :id="`q-block-${q.id}`" class="q-block">
          <div class="q-row">
            <span class="q-order tnum">{{ q.order_num }}</span>
            <div class="q-main">
              <p class="q-stem">{{ q.stem }}</p>
              <p class="q-meta">
                <span v-if="gradingJobStatus === 'queued'" class="badge badge-amber">待批改</span>
                <span v-else-if="gradingJobStatus === 'processing'" class="badge badge-blue">批改中</span>
                <span v-else-if="answeredQids.has(q.id) && gradingJobStatus !== 'completed'" class="badge badge-amber">已作答</span>
                <span v-else-if="noteKind(q) === 'deferred'" class="badge badge-amber">已提交 · 截止后统一批改</span>
                <span v-else-if="pendingQids.has(q.id)" class="badge badge-amber">待老师审核</span>
                <span v-else-if="doneQids.has(q.id)" class="badge badge-green">已完成</span>
                <span v-else class="badge badge-gray">未完成</span>
                <span v-if="scoreByQid[q.id]" class="badge badge-green tnum">得分 {{ fmtScore(scoreByQid[q.id].score) }} / {{ fmtScore(scoreByQid[q.id].max) }} 分</span>
              </p>
            </div>
            <!-- 点按直达图库（v0.9.2）；v0.13.1：已提交的题锁定不再给按钮，
                 要改走页面底部「修改作业」（老师开启允许修改时才有） -->
          <button v-if="!noteKind(q) && !batchLocked" class="btn inline-icon" :disabled="!!submittingMap[q.id]" @click="pickPhoto(q.id)">
              <AppIcon name="camera" :size="16" />
              {{ answeredQids.has(q.id) ? '重新上传作答' : isOffline ? '上传作答照片' : '上传作答图片' }}
            </button>
            <button v-if="flowActive[q.id]" class="btn secondary small" @click="toggleCollapse(q.id)">
              {{ collapsedQids.has(q.id) ? '展开结果' : '收起' }}
            </button>
          </div>

          <!-- 按需挂载拍照流：首次选图后才创建该题组件，已挂载题目仍可直接重拍 -->
          <div v-if="mountedFlowQids.has(q.id)" v-show="!collapsedQids.has(q.id)" class="flow-slot" :class="{ 'has-content': flowActive[q.id] }">
            <PhotoGradeFlow
              :ref="(el) => setFlowRef(q.id, el)"
              :question-id="q.id"
              :question-stem="q.stem"
              direct
              assignment-answer
              :assignment-saving="!!submittingMap[q.id]"
              :assignment-saved="answeredQids.has(q.id)"
              :assignment-error="!!answerErrors[q.id]"
              @answered="onPhotoAnswered(q.id, $event)"
              @active="onFlowActive(q.id, $event)"
            />
          </div>
          <div v-if="answerErrors[q.id]" class="error-msg" style="margin-top: 8px">{{ answerErrors[q.id] }}</div>
          <button v-if="relatedByQid[q.id]" type="button" class="related-mistake-entry" @click="openRelatedMistake(relatedByQid[q.id]!)">
            回看以前错过的同类题 <AppIcon name="chevron-right" :size="14" />
          </button>
          </div>
        </template>
      </div>

      <div v-if="questions.length" class="card assignment-grading-card">
        <h3>整份作业批改</h3>
        <div class="grading-progress-row">
          <span>已完成 {{ answeredCount }} / {{ questions.length }} 题</span>
          <span v-if="gradingJobStatus === 'queued'" class="badge badge-amber">待批改</span>
          <span v-else-if="gradingJobStatus === 'processing'" class="badge badge-blue">批改中 {{ gradingJobProgress }} / {{ gradingJobTotal }}</span>
          <span v-else-if="gradingJobStatus === 'completed'" class="badge badge-green">批改完成</span>
        </div>
        <div v-if="gradingJobStatus === 'queued' || gradingJobStatus === 'processing'" class="grading-progress-track">
          <div class="grading-progress-fill" :style="{ width: `${gradingJobTotal ? Math.round(gradingJobProgress / gradingJobTotal * 100) : 0}%` }"></div>
        </div>
        <p v-if="gradingJobStatus === 'failed'" class="error-msg">批改暂时失败，作答已保留。可以点击下方按钮重新批改。</p>
        <p v-else-if="gradingJobStatus === 'none' || gradingJobStatus === 'draft'" class="grading-wait-hint">
          {{ allAnswersStaged ? '全部题目已完成，请点击提交作业。' : '全部题目完成后可提交作业。' }}
        </p>
        <button
          v-if="allAnswersStaged && (gradingJobStatus === 'failed' || (gradingJobStatus === 'draft' && isOffline))"
          type="button" class="btn" :disabled="!canSubmitAssignment" @click="queueWholeAssignment"
        >{{ batchSubmitting ? '提交中…' : gradingJobStatus === 'failed' ? '重新批改整份作业' : '提交作业' }}</button>
      </div>

      <!-- 修改作业（v0.13.1）：老师勾选「允许修改」后出现在页面最后面——
           已提交的题逐题列出，点「修改」回到那道题重做（截止后自动消失） -->
      <div v-if="canRevise" class="card revise-card">
        <h3>修改作业</h3>
        <p class="card-sub">老师允许你在截止前修改已提交的作答。改完重新提交即可，以最后一次提交为准。</p>
        <div v-for="q in submittedQuestions" :key="q.id" class="revise-row">
          <span class="q-order tnum">{{ q.order_num }}</span>
          <span class="revise-stem">{{ q.stem }}</span>
          <span v-if="noteKind(q) === 'deferred'" class="badge badge-amber">已提交 · 待统一批改</span>
          <span v-else-if="noteKind(q) === 'pending'" class="badge badge-amber">待老师审核</span>
          <span v-else class="badge badge-green">已完成</span>
          <button type="button" class="btn secondary small inline-icon" @click="reviseQuestion(q)">
            <AppIcon name="edit" :size="14" /> 修改
          </button>
        </div>
      </div>

      <div v-if="!questions.length && assignmentId" class="card">
        <div class="empty">这份作业暂时没有可作答的题目。</div>
      </div>
    </template>
    <PreviousMistakeModal :mistake="selectedRelatedMistake" @close="selectedRelatedMistake = null" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useStudentStore } from '../../stores/student'
import type { Assignment, AssignmentDetail, AssignmentGradingStatus, FigureSpec, LatestQuestionSubmissionStatus, Question, RelatedMistake } from '../../api/types'
import AppIcon from '../../components/icons/AppIcon.vue'
import FigureRenderer from '../../components/FigureRenderer.vue'
import HandwritingPad from '../../components/HandwritingPad.vue'
import PhotoGradeFlow from '../../components/PhotoGradeFlow.vue'
import PreviousMistakeModal from '../../components/PreviousMistakeModal.vue'

const student = useStudentStore()
const route = useRoute()
const router = useRouter()

const assignments = ref<Assignment[]>([])
const assignmentId = ref<number | ''>('')
// v0.13.9：「正在交的作业」下拉只列还没交完的——全部题目都已提交的作业
// 不再出现在选项里（后端在作业列表里带了 submitted_count）；选项里顺带
// 标出已交进度，省得点进去才知道还剩几题
const currentAssignment = computed(() => assignments.value.find((a) => a.id === assignmentId.value) ?? null)
const currentFullySubmitted = computed(() => {
  const cur = currentAssignment.value
  return !!cur && cur.question_count > 0 && (cur.submitted_count ?? 0) >= cur.question_count
})
const switchableAssignments = computed(() =>
  assignments.value.filter((a) => (a.submitted_count ?? 0) < a.question_count)
)
// v0.13.10：自制下拉面板的开合与选中（点面板外或按 Esc 收起）
const switchOpen = ref(false)
const switchWrapRef = ref<HTMLElement | null>(null)
let gradingPollHandle: number | null = null
let figurePollHandle: number | null = null
const switchLabel = computed(() => {
  const cur = currentAssignment.value
  if (!cur) return '请选择一份作业…'
  return currentFullySubmitted.value ? `${cur.title}（已全部提交）` : cur.title
})
function chooseAssignment(id: number) {
  switchOpen.value = false
  if (id === assignmentId.value) return
  assignmentId.value = id
  void onAssignmentChange()
}
function onDocClick(e: MouseEvent) {
  if (switchWrapRef.value && !switchWrapRef.value.contains(e.target as Node)) switchOpen.value = false
}
function onDocKey(e: KeyboardEvent) {
  if (e.key === 'Escape') switchOpen.value = false
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onDocKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onDocKey)
  if (gradingPollHandle !== null) window.clearInterval(gradingPollHandle)
  if (figurePollHandle !== null) window.clearInterval(figurePollHandle)
  assignmentLoadToken++
  clearPhotoPreviews()
})
const currentDetail = shallowRef<AssignmentDetail | null>(null) // 整体替换的只读作业详情，避免代理内部大题目列表
const questions = shallowRef<Question[]>([]) // 接口题目只整体替换，避免逐题建立深层响应式代理
const doneQids = ref<Set<number>>(new Set())
const pendingQids = ref<Set<number>>(new Set()) // v0.9.0：最新一次提交在等老师审核的题目
const deferredQids = ref<Set<number>>(new Set()) // v0.13.1：已提交、在等截止后统一批改的题目
const answeredQids = ref<Set<number>>(new Set())
const imageQuestionIds = ref<Set<number>>(new Set())
const gradingJobStatus = ref<AssignmentGradingStatus['status']>('none')
const gradingJobProgress = ref(0)
const gradingJobTotal = ref(0)
const batchSubmitting = ref(false)
const batchLocked = computed(() => gradingJobStatus.value === 'queued' || gradingJobStatus.value === 'processing')
const answeredCount = computed(() => questions.value.filter((q) => answeredQids.value.has(q.id)).length)
const allAnswersStaged = computed(() => questions.value.length > 0 && answeredCount.value === questions.value.length)
const canSubmitAssignment = computed(() => allAnswersStaged.value && !batchSubmitting.value && !batchLocked.value
  && !Object.values(submittingMap.value).some(Boolean)
  && !Object.values(photoPendingFiles.value).some(Boolean)
  && !questions.value.some((q) => !!answerErrors.value[q.id])
  && !questions.value.some((q) => answeredQids.value.has(q.id) && editorOpen.value[q.id] && !isShowingImage(q.id)))
const scoreByQid = ref<Record<number, { score: number; max: number }>>({}) // 评分系统：已通过题目的得分 chip
const relatedByQid = ref<Record<number, RelatedMistake>>({})
const selectedRelatedMistake = ref<RelatedMistake | null>(null)
const loading = ref(false)
const error = ref('')
let assignmentLoadToken = 0

const isOffline = computed(() => currentDetail.value?.mode === 'offline')
const onlineQuestions = computed(() => isOffline.value ? [] : questions.value)
const questionLists = computed(() => {
  if (isOffline.value) {
    return {
      math: questions.value.filter((q) => q.subject === 'math'),
      photo: questions.value,
    }
  }

  return { math: questions.value.filter((q) => q.subject === 'math'), photo: [] }
})
const mathQuestions = computed(() => questionLists.value.math)
const photoQuestions = computed(() => questionLists.value.photo)
function isPhotoQuestion(_q: Question): boolean {
  return isOffline.value
}
function openRelatedMistake(mistake: RelatedMistake) {
  selectedRelatedMistake.value = mistake
}

const headSub = computed(() => {
  if (!currentDetail.value) return '选择作业后逐题作答，全部完成后提交作业。'
  if (isOffline.value) return '逐题拍照保存，全部完成后提交作业。'
  return '可直接输入、使用电子手写或上传作答图片，全部完成后提交作业。'
})
/* ---------- 线下拍照流：点按直达图库（v0.9.2） ---------- */
type FlowHandle = { openPicker: () => void; processFile: (file: File) => Promise<void> }
const flowRefs = new Map<number, FlowHandle | null>()
const photoPickerRef = ref<HTMLInputElement | null>(null)
const mountedFlowQids = shallowRef(new Set<number>())
let pendingPhotoQuestion: { assignmentId: number; questionId: number } | null = null
const flowActive = ref<Record<number, boolean>>({})
const collapsedQids = ref<Set<number>>(new Set())

function setFlowRef(qid: number, el: unknown) {
  const flow = (el as FlowHandle | null) ?? null
  if (flow) flowRefs.set(qid, flow)
  else flowRefs.delete(qid)
}

/** 点「拍照批改」的当下就打开图库，不再先展开一层中间面板 */
function pickPhoto(qid: number) {
  collapsedQids.value.delete(qid)
  const flow = flowRefs.get(qid)
  if (flow) {
    flow.openPicker()
    return
  }
  pendingPhotoQuestion = { assignmentId: Number(assignmentId.value), questionId: qid }
  photoPickerRef.value?.click()
}

async function onPhotoPickerChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  const pending = pendingPhotoQuestion
  pendingPhotoQuestion = null
  if (!file || !pending) return
  if (
    pending.assignmentId !== Number(assignmentId.value) ||
    !questions.value.some((question) => question.id === pending.questionId)
  ) return

  const question = questions.value.find((item) => item.id === pending.questionId)
  if (question && !isPhotoQuestion(question)) {
    void selectOnlinePhoto(pending.questionId, file)
    return
  }
  mountedFlowQids.value = new Set(mountedFlowQids.value).add(pending.questionId)
  await nextTick()
  if (pending.assignmentId !== Number(assignmentId.value)) return
  void flowRefs.get(pending.questionId)?.processFile(file)
}

function onFlowActive(qid: number, active: boolean) {
  flowActive.value[qid] = active
}

function applyGradingStatus(status: AssignmentGradingStatus) {
  gradingJobStatus.value = status.status
  gradingJobProgress.value = status.progress
  gradingJobTotal.value = status.total_questions
  answeredQids.value = new Set(status.answered_question_ids)
  imageQuestionIds.value = new Set(status.image_question_ids ?? [])
}

async function refreshLatestQuestionStatuses(questionIds: number[]) {
  const statuses = await student.fetchLatestQuestionSubmissionStatuses().catch(() => [])
  for (const qid of questionIds) {
    doneQids.value.delete(qid)
    pendingQids.value.delete(qid)
    deferredQids.value.delete(qid)
    delete scoreByQid.value[qid]
  }
  statuses.filter((item) => questionIds.includes(item.question_id)).forEach((item) => {
    if (item.status === 'deferred') deferredQids.value.add(item.question_id)
    else if ((item.review_status ?? 'approved') === 'pending') pendingQids.value.add(item.question_id)
    else doneQids.value.add(item.question_id)
    if (item.score != null && item.max_score != null) {
      scoreByQid.value[item.question_id] = { score: item.score, max: item.max_score }
    }
  })
}

async function refreshGradingStatus(id: number) {
  try {
    const status = await student.fetchAssignmentGradingStatus(id)
    if (id !== Number(assignmentId.value)) return
    applyGradingStatus(status)
    if (status.status === 'queued' || status.status === 'processing') return
    if (gradingPollHandle !== null) window.clearInterval(gradingPollHandle)
    gradingPollHandle = null
    if (status.status === 'completed') {
      await refreshLatestQuestionStatuses(questions.value.map((q) => q.id))
      assignments.value = await student.fetchAssignments().catch(() => assignments.value)
    }
  } catch (e) {
    console.error(e)
  }
}

function startGradingPolling(id: number) {
  if (gradingPollHandle !== null) window.clearInterval(gradingPollHandle)
  gradingPollHandle = window.setInterval(() => { void refreshGradingStatus(id) }, 2500)
}

async function queueWholeAssignment() {
  const id = Number(assignmentId.value)
  if (!id || !canSubmitAssignment.value) return
  const loadToken = assignmentLoadToken
  batchSubmitting.value = true
  error.value = ''
  try {
    const status = await student.submitAssignmentForGrading(id)
    if (loadToken !== assignmentLoadToken || id !== Number(assignmentId.value)) return
    applyGradingStatus(status)
    editorOpen.value = {}
    if (status.status === 'queued' || status.status === 'processing') startGradingPolling(id)
  } catch (e) {
    if (loadToken === assignmentLoadToken && id === Number(assignmentId.value)) {
      error.value = `提交整份作业失败：${errDetail(e) || '请稍后重试。'}`
      console.error(e)
    }
  } finally {
    if (loadToken === assignmentLoadToken) batchSubmitting.value = false
  }
}

let answerSaveVersion = 0
let overlappingAnswerSaves = false
async function saveStagedAnswer(qid: number, payload: { answerText?: string; file?: File }) {
  const id = Number(assignmentId.value)
  const loadToken = assignmentLoadToken
  if (!id || submittingMap.value[qid] || batchLocked.value || batchSubmitting.value) return
  if (Object.values(submittingMap.value).some(Boolean)) overlappingAnswerSaves = true
  ++answerSaveVersion
  submittingMap.value[qid] = true
  answerErrors.value[qid] = ''
  try {
    const status = await student.stageAssignmentAnswer(id, qid, payload)
    if (loadToken !== assignmentLoadToken || id !== Number(assignmentId.value)) return
    applyGradingStatus(status)
    const question = questions.value.find((q) => q.id === qid)
    const onlineImage = !!payload.file && !!question && !isPhotoQuestion(question)
    editorOpen.value[qid] = onlineImage
    handwritingOpen.value[qid] = false
    if (onlineImage) {
      delete photoPendingFiles.value[qid]
      photoTextMode.value[qid] = false
    } else if (!payload.file) {
      delete photoPendingFiles.value[qid]
      photoTextMode.value[qid] = false
      clearPhotoPreview(qid)
    }
    if (payload.file) clearHandwritingDraft(qid)
  } catch (e) {
    if (loadToken === assignmentLoadToken && id === Number(assignmentId.value)) {
      answerErrors.value[qid] = `保存作答失败：${errDetail(e) || '请稍后重试。'}`
      console.error(e)
    }
  } finally {
    if (loadToken === assignmentLoadToken) {
      submittingMap.value[qid] = false
      if (overlappingAnswerSaves && !Object.values(submittingMap.value).some(Boolean)) {
        overlappingAnswerSaves = false
        const saveVersion = answerSaveVersion
        try {
          const status = await student.fetchAssignmentGradingStatus(id)
          if (loadToken === assignmentLoadToken && saveVersion === answerSaveVersion && id === Number(assignmentId.value)) applyGradingStatus(status)
        } catch {
          // Individual saves remain valid even if refreshing their combined status fails.
        }
      }
    }
  }
}

function onPhotoAnswered(qid: number, file: File) {
  void saveStagedAnswer(qid, { file })
}

function toggleCollapse(qid: number) {
  if (collapsedQids.value.has(qid)) collapsedQids.value.delete(qid)
  else collapsedQids.value.add(qid)
}

/* ---------- 线上在线作答（v0.9.2） ---------- */
const MAX_STEPS = 20 // 与后端 SubmissionCreate.steps 上限一致
const drafts = ref<Record<number, string>>({})
const editorOpen = ref<Record<number, boolean>>({})
const submittingMap = ref<Record<number, boolean>>({})
const answerErrors = ref<Record<number, string>>({})
const gutterScroll = ref<Record<number, number>>({})
const loadedDraftQids = new Set<number>()
const handwritingOpen = ref<Record<number, boolean>>({})
const photoPreviews = ref<Record<number, string>>({})
const photoLoadErrors = ref<Record<number, string>>({})
const photoLoading = ref<Record<number, boolean>>({})
const photoPendingFiles = ref<Record<number, File | undefined>>({})
const photoTextMode = ref<Record<number, boolean>>({})
let photoRequestSerial: Record<number, number> = {}

function clearPhotoPreview(qid: number) {
  const url = photoPreviews.value[qid]
  if (url) URL.revokeObjectURL(url)
  delete photoPreviews.value[qid]
  photoRequestSerial[qid] = (photoRequestSerial[qid] ?? 0) + 1
  delete photoLoadErrors.value[qid]
  delete photoLoading.value[qid]
}
function clearPhotoPreviews() {
  for (const url of Object.values(photoPreviews.value)) URL.revokeObjectURL(url)
  photoPreviews.value = {}
  photoLoadErrors.value = {}
  photoLoading.value = {}
  photoPendingFiles.value = {}
  photoTextMode.value = {}
  photoRequestSerial = {}
}
function isShowingImage(qid: number): boolean {
  return !photoTextMode.value[qid] && (!!photoPreviews.value[qid] || imageQuestionIds.value.has(qid))
}
async function loadOnlinePhoto(id: number, qid: number) {
  if (!id || !imageQuestionIds.value.has(qid) || photoPreviews.value[qid] || photoLoading.value[qid]) return
  const loadToken = assignmentLoadToken
  const serial = (photoRequestSerial[qid] ?? 0) + 1
  photoRequestSerial[qid] = serial
  photoLoading.value[qid] = true
  delete photoLoadErrors.value[qid]
  try {
    const blob = await student.fetchStagedAnswerImage(id, qid)
    if (loadToken !== assignmentLoadToken || id !== Number(assignmentId.value) || photoRequestSerial[qid] !== serial) return
    photoPreviews.value[qid] = URL.createObjectURL(blob)
  } catch {
    if (loadToken === assignmentLoadToken && id === Number(assignmentId.value) && photoRequestSerial[qid] === serial) {
      photoLoadErrors.value[qid] = '作答图片暂时无法加载。'
    }
  } finally {
    if (loadToken === assignmentLoadToken && photoRequestSerial[qid] === serial) delete photoLoading.value[qid]
  }
}
async function selectOnlinePhoto(qid: number, file: File) {
  if (submittingMap.value[qid] || batchLocked.value || batchSubmitting.value) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    answerErrors.value[qid] = '仅支持 jpg / png / webp 格式的作答照片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    answerErrors.value[qid] = '图片太大了（超过 10MB），请压缩后再试。'
    return
  }
  clearPhotoPreview(qid)
  photoPreviews.value[qid] = URL.createObjectURL(file)
  photoPendingFiles.value[qid] = file
  photoTextMode.value[qid] = false
  handwritingOpen.value[qid] = false
  editorOpen.value[qid] = true
  await saveStagedAnswer(qid, { file })
}
function retryOnlinePhoto(qid: number) {
  const file = photoPendingFiles.value[qid]
  if (file) void saveStagedAnswer(qid, { file })
}
function useTextAnswer(qid: number) {
  delete photoPendingFiles.value[qid]
  clearPhotoPreview(qid)
  photoTextMode.value[qid] = true
  editorOpen.value[qid] = true
  answerErrors.value[qid] = ''
  restoreDraft(qid)
}
function restorePhotoAnswer(qid: number) {
  photoTextMode.value[qid] = false
  editorOpen.value[qid] = true
  answerErrors.value[qid] = ''
}

type HandwritingPadHandle = { clear: () => void }
const handwritingRefs = new Map<number, HandwritingPadHandle>()

const draftKey = (qid: number) => `remedi-answer-draft-${qid}`
const handwritingDraftKey = (qid: number) => `remedi-handwriting-draft-${qid}`

function setHandwritingRef(qid: number, el: unknown) {
  if (el) handwritingRefs.set(qid, el as HandwritingPadHandle)
  else handwritingRefs.delete(qid)
}

function clearHandwritingDraft(qid: number) {
  handwritingRefs.get(qid)?.clear()
  try { localStorage.removeItem(handwritingDraftKey(qid)) } catch { /* storage is optional */ }
}

function toggleHandwriting(qid: number) {
  handwritingOpen.value[qid] = !handwritingOpen.value[qid]
}

function restoreDraft(qid: number) {
  if (loadedDraftQids.has(qid)) return
  loadedDraftQids.add(qid)
  const saved = localStorage.getItem(draftKey(qid))
  if (saved) drafts.value[qid] = saved
}

function onDraftInput(qid: number, e: Event) {
  const text = (e.target as HTMLTextAreaElement).value
  drafts.value[qid] = text
  // 草稿按题目存本机，交完清除（见 submitAnswer）
  if (text) localStorage.setItem(draftKey(qid), text)
  else localStorage.removeItem(draftKey(qid))
}

async function submitHandwriting(q: Question, file: File) {
  if (submittingMap.value[q.id]) return
  await selectOnlinePhoto(q.id, file)
}

function onEditorScroll(qid: number, e: Event) {
  gutterScroll.value[qid] = (e.target as HTMLTextAreaElement).scrollTop
}

function clearDraft(qid: number) {
  drafts.value[qid] = ''
  localStorage.removeItem(draftKey(qid))
  answerErrors.value[qid] = ''
}

/* ---------- 线上做题板（v0.13.1）：一题一屏 + 符号栏 + 答题卡 ---------- */
const currentIdx = ref(0)
const cardOpen = ref(false)
const boardTextarea = ref<HTMLTextAreaElement | null>(null)
const currentQ = computed(() => onlineQuestions.value[currentIdx.value] ?? null)
watch(() => [Number(assignmentId.value), currentQ.value?.id ?? 0, imageQuestionIds.value.has(currentQ.value?.id ?? -1), !!photoTextMode.value[currentQ.value?.id ?? -1], gradingJobStatus.value] as const,
  ([id, qid, hasImage, textMode, status]) => {
    if (id && qid && hasImage && !textMode && status !== 'completed' && status !== 'queued' && status !== 'processing') void loadOnlinePhoto(id, qid)
  }, { flush: 'post' })
const currentDraftMetrics = computed(() => {
  const questionId = currentQ.value?.id
  const text = questionId == null ? '' : drafts.value[questionId] ?? ''
  let lineCount = 1
  let stepCount = 0
  let lineStart = 0

  while (lineStart <= text.length) {
    const newlineIndex = text.indexOf('\n', lineStart)
    const lineEnd = newlineIndex < 0 ? text.length : newlineIndex
    if (text.slice(lineStart, lineEnd).trim()) stepCount += 1
    if (newlineIndex < 0) break
    lineCount += 1
    lineStart = newlineIndex + 1
  }

  return { lineCount, stepCount }
})

/** 本题的提交状态卡类型：本次会话刚提交的优先，其次历史提交状态；null = 还没提交过 */
function noteKind(q: Question): 'pending' | 'approved' | 'deferred' | null {
  if (deferredQids.value.has(q.id)) return 'deferred'
  if (pendingQids.value.has(q.id)) return 'pending'
  if (doneQids.value.has(q.id)) return 'approved'
  return null
}

/* ---------- 修改作业（v0.13.1）：教师勾选允许修改时，页面底部出现已提交清单 ---------- */
const groupById = computed(() => new Map((currentDetail.value?.groups ?? []).map((g) => [g.id, g])))
function groupStemOf(q: Question): string | undefined {
  return q.group_id ? groupById.value.get(q.group_id)?.stem : undefined
}
function groupDiagramOf(q: Question): FigureSpec | undefined {
  return q.group_id ? groupById.value.get(q.group_id)?.diagram ?? undefined : undefined
}
function groupFigurePending(q: Question): boolean {
  const status = q.group_id ? groupById.value.get(q.group_id)?.diagram_status : null
  return status === 'queued' || status === 'processing'
}
function startFigurePolling(id: number, loadToken: number) {
  if (figurePollHandle !== null) window.clearInterval(figurePollHandle)
  figurePollHandle = null
  if (!currentDetail.value?.groups?.some((g) => ['queued', 'processing', 'failed'].includes(g.diagram_status ?? ''))) return
  let running = false
  figurePollHandle = window.setInterval(async () => {
    if (running) return
    running = true
    try {
      const detail = await student.fetchAssignmentDetail(id)
      if (loadToken !== assignmentLoadToken || Number(assignmentId.value) !== id) return
      if (currentDetail.value) currentDetail.value = { ...currentDetail.value, groups: detail.groups }
      if (!detail.groups?.some((g) => ['queued', 'processing', 'failed'].includes(g.diagram_status ?? ''))) {
        if (figurePollHandle !== null) window.clearInterval(figurePollHandle)
        figurePollHandle = null
      }
    } catch { /* 保留已有题目并在下次轮询时重试 */ }
    finally { running = false }
  }, 4000)
}
function showGroupBanner(q: Question, i: number, list: Question[] = mathQuestions.value): boolean {
  if (!q.group_id) return false
  const prev = list[i - 1]
  return !prev || prev.group_id !== q.group_id
}
const submittedQuestions = computed(() => questions.value.filter((q) => noteKind(q)))
/** 还能修改：老师开了允许修改、没到截止、且已有提交 */
const canRevise = computed(() => {
  if (!currentDetail.value?.allow_revision) return false
  const dl = currentDetail.value.deadline
  if (dl && new Date(dl).getTime() <= Date.now()) return false
  return submittedQuestions.value.length > 0
})
function reviseQuestion(q: Question) {
  if (isPhotoQuestion(q)) {
    document.getElementById(`q-block-${q.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    pickPhoto(q.id)
    return
  }
  const idx = onlineQuestions.value.findIndex((x) => x.id === q.id)
  if (idx >= 0) gotoQuestion(idx)
  // 强制重开编辑器，改完后重新保存答案。
  editorOpen.value[q.id] = true
}

function gotoQuestion(i: number) {
  const idx = Math.max(0, Math.min(onlineQuestions.value.length - 1, i))
  currentIdx.value = idx
  cardOpen.value = false
  const q = onlineQuestions.value[idx]
  if (q) restoreDraft(q.id)
  // 还没提交过的题直接展开编辑器；已提交的先看状态卡（可再交一次）
  if (q && !noteKind(q) && !answeredQids.value.has(q.id) && !batchLocked.value) editorOpen.value[q.id] = true
}

/** 符号栏：只放后端解析器认得的符号（× ÷ · ² ³ 归一化在 mathparse，
 *  √/π/− 于 v0.13.1 补齐归一化）；√ 插入成 √( 光标停在括号里，接着打数字即可 */
interface SymbolDef { label: string; text: string; caretBack?: number }
const SYMBOLS: SymbolDef[] = [
  { label: '(', text: '(' },
  { label: ')', text: ')' },
  { label: '+', text: '+' },
  { label: '−', text: '−' },
  { label: '×', text: '×' },
  { label: '÷', text: '÷' },
  { label: '=', text: '=' },
  { label: '·', text: '·' },
  { label: 'x²', text: '²' },
  { label: 'x³', text: '³' },
  { label: 'xⁿ', text: '^' },
  { label: '√', text: '√()', caretBack: 1 },
  { label: 'π', text: 'π' }
]

/** 在光标处插入符号，插完把光标放回插入点（√ 时落在括号内），草稿同步落盘 */
function insertSymbol(s: SymbolDef) {
  const q = currentQ.value
  if (!q) return
  const ta = boardTextarea.value
  const cur = drafts.value[q.id] ?? ''
  const start = ta ? ta.selectionStart : cur.length
  const end = ta ? ta.selectionEnd : cur.length
  const next = cur.slice(0, start) + s.text + cur.slice(end)
  drafts.value[q.id] = next
  if (next) localStorage.setItem(draftKey(q.id), next)
  else localStorage.removeItem(draftKey(q.id))
  void nextTick(() => {
    if (!ta) return
    ta.focus()
    const pos = start + s.text.length - (s.caretBack ?? 0)
    ta.setSelectionRange(pos, pos)
    gutterScroll.value[q.id] = ta.scrollTop
  })
}

function errDetail(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : ''
}

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

/** 在线提交：与拍照完全同链——后端先 AI 诊断，再进教师待审核（3.3） */
async function submitAnswer(q: Question) {
  const steps = (drafts.value[q.id] ?? '').split('\n').map((s) => s.trim()).filter(Boolean)
  if (!steps.length) {
    answerErrors.value[q.id] = q.subject === 'math' ? '先写下你的解题步骤再提交。' : '请先输入作答内容。'
    return
  }
  if (q.subject === 'math' && steps.length > MAX_STEPS) {
    answerErrors.value[q.id] = `步骤最多 ${MAX_STEPS} 步，请把几步合并一下再提交。`
    return
  }
  await saveStagedAnswer(q.id, { answerText: steps.join('\n') })
}

/* ---------- 作业装载与状态 ---------- */

async function loadQuestions(id: number, loadToken: number) {
  const emptyRelatedMistakes: Record<string, RelatedMistake | null> = {}
  const relatedPromise = currentAssignment.value?.photo_required === false
    ? Promise.resolve(emptyRelatedMistakes)
    : student.fetchRelatedMistakesForAssignment(id).catch(() => emptyRelatedMistakes)
  const detail = await student.fetchAssignmentDetail(id)
  if (loadToken !== assignmentLoadToken || Number(assignmentId.value) !== id) return detail
  questions.value = detail.questions
  currentDetail.value = detail
  startFigurePolling(id, loadToken)
  const relatedByQuestion = await relatedPromise
  if (loadToken !== assignmentLoadToken || Number(assignmentId.value) !== id) return detail
  const related: Record<number, RelatedMistake> = {}
  Object.entries(relatedByQuestion).forEach(([questionId, mistake]) => {
    if (mistake) related[Number(questionId)] = mistake
  })
  relatedByQid.value = related
  const gradingStatus = await student.fetchAssignmentGradingStatus(id).catch(() => null)
  if (loadToken !== assignmentLoadToken || Number(assignmentId.value) !== id) return detail
  if (gradingStatus) {
    applyGradingStatus(gradingStatus)
    if (gradingStatus.status === 'queued' || gradingStatus.status === 'processing') {
      startGradingPolling(id)
    } else if (gradingStatus.status === 'completed') {
      await refreshLatestQuestionStatuses(detail.questions.map((q) => q.id))
    }
  }
  // 在线作业只在题目首次进入做题板时读取本机草稿，避免逐题同步访问存储。
  if (detail.mode !== 'offline') {
    // 做题板初始定位：优先地址栏 ?q=<题目 id>（AI 简报「去完成」跳入时带），
    // 其次第一道未完成题；定位到的题若还没提交过，直接展开编辑器
    const qs = onlineQuestions.value
    const wantQid = Number(route.query.q)
    let requestedIndex = -1
    let firstUnfinishedIndex = -1
    for (let index = 0; index < qs.length; index++) {
      const question = qs[index]
      if (question.id === wantQid) {
        requestedIndex = index
        break
      }
      if (
        firstUnfinishedIndex < 0 &&
        !doneQids.value.has(question.id) &&
        !pendingQids.value.has(question.id) &&
        !answeredQids.value.has(question.id)
      ) {
        firstUnfinishedIndex = index
      }
    }
    const idx = requestedIndex >= 0 ? requestedIndex : firstUnfinishedIndex
    currentIdx.value = idx >= 0 ? idx : 0
    const q = qs[currentIdx.value]
    if (q) restoreDraft(q.id)
    if (q && !noteKind(q) && !answeredQids.value.has(q.id) && !batchLocked.value) editorOpen.value[q.id] = true
  }
  return detail
}

async function selectAssignment(id: number) {
  const loadToken = ++assignmentLoadToken
  if (figurePollHandle !== null) window.clearInterval(figurePollHandle)
  figurePollHandle = null
  if (gradingPollHandle !== null) window.clearInterval(gradingPollHandle)
  gradingPollHandle = null
  answeredQids.value = new Set()
  imageQuestionIds.value = new Set()
  clearPhotoPreviews()
  batchSubmitting.value = false
  submittingMap.value = {}
  overlappingAnswerSaves = false
  gradingJobStatus.value = 'none'
  gradingJobProgress.value = 0
  gradingJobTotal.value = 0
  error.value = ''
  questions.value = []
  relatedByQid.value = {}
  currentDetail.value = null
  mountedFlowQids.value = new Set()
  pendingPhotoQuestion = null
  flowActive.value = {}
  collapsedQids.value = new Set()
  loadedDraftQids.clear()
  editorOpen.value = {}
  handwritingOpen.value = {}
  handwritingRefs.clear()
  answerErrors.value = {}
  if (!id) return
  try {
    await loadQuestions(id, loadToken)
  } catch (e) {
    if (loadToken === assignmentLoadToken && Number(assignmentId.value) === id) {
      error.value = '作业详情加载失败。'
      console.error(e)
    }
  }
}

async function onAssignmentChange() {
  const id = Number(assignmentId.value)
  // 地址栏同步当前作业，刷新/分享链接都落回这份作业
  router.replace({ query: id ? { assignment_id: id } : {} })
  await selectAssignment(id)
}

onMounted(async () => {
  loading.value = true
  try {
    const [list, statuses] = await Promise.all([
      student.fetchAssignments(),
      student.fetchLatestQuestionSubmissionStatuses().catch(() => [])
    ])
    assignments.value = list
    // 后端按题目只返回最新提交，状态不受提交历史分页上限影响。
    statuses.forEach((s: LatestQuestionSubmissionStatus) => {
      const qid = s.question_id
      if (s.status === 'deferred') deferredQids.value.add(qid)
      else if ((s.review_status ?? 'approved') === 'pending') pendingQids.value.add(qid)
      else doneQids.value.add(qid)
    })
    const scores: Record<number, { score: number; max: number }> = {}
    statuses.forEach((s) => {
      if (s.score !== null && s.score !== undefined && s.max_score !== null && s.max_score !== undefined) {
        scores[s.question_id] = { score: s.score, max: s.max_score }
      }
    })
    scoreByQid.value = scores
    const presetId = Number(route.query.assignment_id)
    if (presetId && list.some((a) => a.id === presetId)) {
      assignmentId.value = presetId
      const loadToken = ++assignmentLoadToken
      try {
        await loadQuestions(presetId, loadToken)
      } catch {
        if (loadToken === assignmentLoadToken && Number(assignmentId.value) === presetId) {
          error.value = '该作业不存在或已失效，请重新选择。'
        }
      }
    } else if (presetId) {
      error.value = '该作业不存在或已失效，请重新选择。'
    }
  } catch (e) {
    error.value = '作业列表加载失败，请确认后端已启动。'
    console.error(e)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* 作业切换条（v0.9.0）：sticky 钉顶，与下方卡片拉开间距和层级 */
.switch-bar {
  position: sticky;
  top: 12px;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  box-shadow: var(--shadow-md);
}
.switch-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}
/* v0.13.10：自制下拉面板（替代原生 select，展开列表也全站同款样式） */
.switch-select-wrap { position: relative; flex: 1; min-width: 200px; }
.switch-select {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 9px 12px; border: 1.5px solid var(--border); border-radius: 10px;
  background: #fff; font-size: 14px; color: var(--text); cursor: pointer; text-align: left;
}
.switch-select:hover { border-color: #BFDBFE; }
.switch-select:focus-visible { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-50); }
.switch-select-text { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.switch-chevron { flex-shrink: 0; color: var(--text-3); transition: transform .15s ease; }
.switch-chevron.open { transform: rotate(180deg); }
.switch-menu {
  position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 70;
  background: #fff; border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow-md); padding: 6px; max-height: 320px; overflow-y: auto;
}
.switch-option {
  width: 100%; display: flex; align-items: center; gap: 10px; text-align: left;
  padding: 9px 10px; border: none; background: transparent; border-radius: 8px; cursor: pointer;
}
.switch-option:hover:not(:disabled) { background: var(--primary-50); }
.switch-option.active { background: var(--primary-50); }
.switch-option:disabled { cursor: default; opacity: .55; }
.switch-option-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.switch-option-title { font-size: 14px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.switch-option-meta { font-size: 12px; color: var(--text-3); }
.switch-option-check { flex-shrink: 0; color: var(--primary); }
.switch-menu-empty { padding: 10px; font-size: 13px; color: var(--text-2); }
.switch-all {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  color: var(--primary);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
@media (max-width: 960px) {
  /* 移动端顶栏高 52px，切换条贴在它下方 */
  .switch-bar { top: 60px; }
}
.assign-info { background: var(--primary-50); border-color: #DBEAFE; box-shadow: none; }
.assign-info .kp { color: var(--text-2); font-size: 13px; margin-top: 4px; }
.assign-info .deadline-line { color: #B45309; font-weight: 600; }
.assignment-grading-card { margin-top: 16px; }
.grading-progress-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 12px 0 8px; color: var(--text-2); font-size: 14px; }
.grading-progress-track { height: 8px; overflow: hidden; border-radius: 999px; background: #E8EDF5; margin: 8px 0 12px; }
.grading-progress-fill { height: 100%; border-radius: inherit; background: var(--primary); transition: width .25s ease; }
.grading-wait-hint { margin: 10px 0; color: var(--text-2); font-size: 13px; }
.q-block { border-bottom: 1px solid #F1F3F6; padding-bottom: 12px; }
.q-block:last-child { border-bottom: none; padding-bottom: 0; }
.q-row {
  display: flex; align-items: center; gap: 14px;
  padding: 12px 4px 0;
}
.q-order {
  width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
  background: var(--primary-50); color: var(--primary);
  font-weight: 700; font-size: 13.5px;
  display: flex; align-items: center; justify-content: center;
}
.q-main { flex: 1; min-width: 0; }
.q-stem { font-size: 16px; font-weight: 600; }
.q-meta { margin-top: 4px; }
/* ---------- 线上做题板（v0.13.1） ---------- */
.board-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; flex-wrap: wrap;
}
.board-progress { font-size: 13px; font-weight: 600; color: var(--text-2); }
.board-status { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.board-stem {
  font-size: 19px; font-weight: 600; line-height: 1.75;
  color: var(--text); margin: 12px 0 2px;
}
.board-editor { margin: 12px 0 2px; }
.board-note { margin: 14px 0 2px; }
/* 大题材料块（做题板 + 线下列表共用） */
.board-group-stem, .group-stem-banner {
  background: var(--primary-50); border: 1px solid #DBEAFE; border-radius: 10px;
  padding: 11px 14px; margin-top: 12px;
  font-size: 14.5px; line-height: 1.7; color: var(--text);
}
.group-stem-content {
  display: grid; grid-template-columns: minmax(0, 1fr); align-items: center; gap: 12px;
  margin-top: 4px;
}
.group-stem-content.has-diagram { grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr); gap: 18px; }
.group-stem-content p { min-width: 0; }
.group-stem-content :deep(.question-figure) { width: 100%; max-width: none; margin: 0; }
.board-group-tag {
  display: inline-block; font-size: 11.5px; font-weight: 700; color: var(--primary);
  letter-spacing: 0.04em;
}
.group-stem-banner { margin: 14px 0 2px; }
@media (max-width: 760px) {
  .group-stem-content.has-diagram { grid-template-columns: minmax(0, 1fr); gap: 8px; }
  .group-stem-content.has-diagram :deep(.question-figure) { max-width: 480px; margin: 0 auto; }
}
/* 修改作业区（v0.13.1） */
.revise-card { margin-top: 16px; }
.revise-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 4px; border-bottom: 1px solid #F1F3F6;
}
.revise-row:last-child { border-bottom: none; }
.revise-stem { flex: 1; min-width: 0; font-size: 14.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.symbol-bar { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.symbol-btn {
  min-width: 38px; height: 34px; padding: 0 9px;
  border: 1.5px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text);
  font-size: 15px; font-weight: 600; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
}
.symbol-btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-50); }
.symbol-btn:active { transform: translateY(1px); }
.board-nav {
  position: relative;
  display: flex; align-items: center; gap: 10px;
  margin-top: 16px; padding-top: 14px;
  border-top: 1px solid #F1F3F6;
}
.related-mistake-entry { display: inline-flex; align-items: center; gap: 4px; margin: 12px 0 4px; padding: 0; border: 0; background: transparent; color: var(--primary); font: inherit; font-size: 13px; font-weight: 650; cursor: pointer; }
.related-mistake-entry:hover { text-decoration: underline; }
.board-nav-right { display: flex; gap: 8px; margin-left: auto; }
.answer-card-pop {
  position: absolute; left: 0; bottom: calc(100% + 8px); z-index: 40;
  background: #fff; border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow-md); padding: 14px;
  max-width: min(400px, 92vw);
}
.answer-card-grid { display: flex; flex-wrap: wrap; gap: 8px; max-width: 352px; }
.answer-cell {
  width: 36px; height: 36px; border-radius: 9px;
  border: 1.5px solid var(--border); background: #fff;
  font-size: 14px; font-weight: 600; color: var(--text-2); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
}
.answer-cell:hover { border-color: var(--primary); color: var(--primary); }
.answer-cell.done { background: #ECFDF5; border-color: #A7F3D0; color: #065F46; }
.answer-cell.pending { background: var(--amber-bg); border-color: #FDE68A; color: #92400E; }
.answer-cell.current { border-color: var(--primary); color: var(--primary); box-shadow: 0 0 0 2px var(--primary-50); }
.answer-card-legend {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-top: 11px; font-size: 12px; color: var(--text-3);
}
.answer-card-legend .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-left: 6px; }
.answer-card-legend .dot:first-child { margin-left: 0; }
.answer-card-legend .dot.done { background: #10B981; }
.answer-card-legend .dot.pending { background: var(--amber); }
.answer-card-legend .dot.todo { background: #CBD5E1; }
/* 拍照流槽位：idle 时不占位，有内容才让组件自带的上边距生效 */
.flow-slot :deep(.pgf) { margin-top: 0; }
.flow-slot.has-content :deep(.pgf) { margin-top: 12px; }
/* 在线作答编辑器（v0.9.2）：左侧行号槽 + 文本域，行高严格对齐 */
.answer-editor { margin: 12px 4px 2px; }
.answer-mode-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.editor-wrap {
  display: flex;
  height: 208px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}
 .image-answer-wrap { align-items: center; justify-content: center; min-height: 208px; height: auto; max-height: 520px; padding: 12px; }
.answer-image { display: block; max-width: 100%; max-height: 490px; object-fit: contain; }
.image-load-error { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; color: var(--text-2); }
.editor-wrap:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-50); }
.editor-gutter {
  flex-shrink: 0;
  width: 40px;
  padding: 10px 0;
  background: var(--bg);
  border-right: 1px solid #EDF0F4;
  overflow: hidden;
  text-align: right;
}
.editor-gutter-inner { display: flex; flex-direction: column; will-change: transform; }
.editor-gutter-inner span {
  height: 26px; line-height: 26px;
  padding-right: 10px;
  font-size: 12.5px; color: var(--text-3);
  user-select: none;
}
.answer-textarea {
  flex: 1; min-width: 0;
  height: 100%;
  border: none; border-radius: 0;
  padding: 10px 12px;
  font-size: 14.5px; line-height: 26px;
  resize: none;
  background: transparent;
}
.answer-textarea:focus { outline: none; border: none; box-shadow: none; }
.editor-meta {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  margin-top: 7px; font-size: 12.5px; color: var(--text-3);
}
.editor-warn { color: var(--amber); font-weight: 600; }
.editor-saved { color: var(--text-3); }
/* 待老师审核状态盒（与 PhotoGradeFlow 内同一套语义，保持双端观感一致） */
.review-pending-box {
  display: flex; gap: 11px; align-items: flex-start;
  background: var(--amber-bg); border: 1px solid #FDE68A; border-radius: 10px;
  padding: 13px 15px; margin: 12px 4px 2px;
}
.review-pending-icon { width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0; background: #fff; color: var(--amber); display: flex; align-items: center; justify-content: center; }
.review-pending-title { font-size: 14.5px; font-weight: 700; color: #92400E; }
.review-pending-sub { font-size: 13px; color: #92400E; opacity: 0.85; margin-top: 2px; }
.submit-ok-line {
  display: flex; align-items: center; gap: 6px;
  margin: 12px 4px 2px; font-size: 14px; color: #065F46;
}
</style>
