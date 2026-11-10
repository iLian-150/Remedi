<!-- 教师端：发布作业（v0.2.0 新增；v0.5.0 双模式）
     发布分两种模式（v0.5.0）：
       - 线上作业：手动录题 / 逐题拍照识别，学生逐题拍照批改（原流程）。
       - 线下作业 · 练习册：从练习册知识库选一本（可现场上传整本 PDF）+ 填页码范围 + 截止时间，
         再拍照上传题目页识别成草稿题，教师检查修改后发布；学生作答方式与线上完全一致。
     契约：POST /api/teacher/assignments（4.7，v0.5.0 加 mode/workbook_id/page_range/deadline）、
           练习册知识库 4.15~4.17、拍照识别 4.9。数学线上作答用公式板，其他学科通过视觉模型拍照批改。 -->
<template>
  <div class="page publish-page" :class="{ 'is-embedded': embedded, 'is-chat-workflow': chatWorkflow, 'is-chat-workflow-collapsed': chatWorkflow && chatWorkflowCollapsed }">
    <div v-if="chatWorkflow" class="chat-workflow-head">
      <span><AppIcon name="sparkles" :size="16" /> 发布作业草稿</span>
      <button
        type="button"
        class="btn small secondary"
        :aria-expanded="!chatWorkflowCollapsed"
        @click="chatWorkflowCollapsed = !chatWorkflowCollapsed"
      >{{ chatWorkflowCollapsed ? '展开' : '收起' }}</button>
    </div>
    <template v-if="!chatWorkflowCollapsed">
    <div v-if="(!embedded || step === 'form') && !chatWorkflow" class="page-head publish-head">
      <div v-if="!embedded" class="ph-main">
        <router-link to="/teacher/assignments" class="back-link"><AppIcon name="chevron-left" :size="16" /> 返回作业入口</router-link>
      </div>
    </div>

    <!-- v0.13.11：红色警示改顶部悬浮 toast——不再占位把表单往下推，
         出现 5 秒后自动消失（计时逻辑在 script 的 watch(error)） -->
    <transition name="toast-fade">
      <div v-if="error" class="error-toast" role="alert">
        <AppIcon name="alert" :size="16" />
        <span>{{ error }}</span>
      </div>
    </transition>
    <div v-if="ok && !embedded" class="ok-msg">发布成功，正在跳转到作业列表…</div>

    <!-- 第一级：选择发布方式（v0.12.0 两级化：点卡进入第二级表单，不再同页堆叠） -->
    <PublishModeCards v-if="step === 'choose'" @choose="chooseMode" />

    <!-- 第二级：发布表单 -->
    <template v-if="step === 'form'">
    <!-- 线下模式：练习册与页码（v0.13.3：书本不再常驻表单——选书做成一个按钮，
         点开书架面板才陈列封面选书；选书按钮与页码输入并在同一行） -->
    <div v-if="mode === 'offline'" class="card">
      <!-- v0.13.4：整卡折叠——默认收起只剩标题行（带已选摘要），点标题行才展开选书/填页码 -->
      <button type="button" class="fold-head" :aria-expanded="wbOpen" @click="wbOpen = !wbOpen">
        <h3 style="margin: 0">练习册与范围</h3>
        <span class="fold-sum">{{ wbSummary }}</span>
        <AppIcon :name="wbOpen ? 'chevron-down' : 'chevron-right'" :size="16" />
      </button>
      <div v-if="wbOpen" class="fold-body">
      <div class="wb-pick-row">
        <div class="form-row">
          <label>选择练习册</label>
          <button type="button" class="wb-pick-btn" @click="shelfOpen = true">
            <AppIcon name="book" :size="17" />
            <span class="wb-pick-name">{{ selectedWorkbook ? selectedWorkbook.title : (workbooks.length ? '点这里从书架选一本' : '书架还是空的，点这里上传') }}</span>
            <AppIcon name="chevron-right" :size="15" />
          </button>
        </div>
        <div class="form-row">
          <label>页码 / 题号范围</label>
          <input v-model="pageRange" type="text" placeholder="例如：第 12-14 页 第 1-8 题" maxlength="64" />
        </div>
      </div>
      <input ref="wbFileRef" type="file" accept="application/pdf" hidden @change="onWorkbookFile" />
      <!-- 按页提题（v0.13.0）：把所选页渲染成图，视觉 AI 逐页拆成草稿题 -->
      <div class="extract-row">
        <button
          type="button"
          class="btn secondary inline-icon"
          :disabled="!workbookId || !pageRange.trim() || extracting"
          @click="extractFromPdf"
        >
          <AppIcon name="sparkles" :size="15" /> {{ extracting ? '正在逐页识别…' : '从 PDF 自动识别这些页的题目' }}
        </button>
        <span class="hint">填好上面的页码后点这里：系统把这几页渲染成图，用视觉 AI 拆成草稿题填到下方题目卡；一次最多 8 页，识别结果是草稿，发布前请逐题检查。没识别到的页可以再用拍照补录。</span>
      </div>
      <p v-if="extractNote" class="ok-msg" style="margin-top: 10px; margin-bottom: 0">{{ extractNote }}</p>
      </div>
    </div>

    <!-- 书架选书面板（v0.13.3）：点「选择练习册」才打开，封面陈列只在这里出现；
         上传 / 查看 / 删除也都收在面板里，表单常驻区只留一行选书按钮 -->
    <div v-if="shelfOpen" class="shelf-mask" @click.self="shelfOpen = false">
      <div class="shelf-panel">
        <div class="shelf-head">
          <h3 style="margin: 0">从书架选择练习册</h3>
          <button type="button" class="btn small secondary" @click="shelfOpen = false">关闭</button>
        </div>
        <div v-if="workbooks.length" class="shelf-grid">
          <button
            v-for="w in workbooks"
            :key="w.id"
            type="button"
            class="wb-thumb shelf-thumb"
            :class="{ active: Number(workbookId) === w.id }"
            :title="w.title"
            @click="pickWorkbook(w)"
          >
            <img v-if="w.cover_url" :src="w.cover_url" :alt="w.title" />
            <span v-else class="wb-thumb-spine"><AppIcon name="book" :size="22" /></span>
            <span class="wb-thumb-name">{{ w.title }}</span>
          </button>
        </div>
        <p v-else class="hint" style="line-height: 1.6">书架还是空的。把整本练习册的 PDF 传进来，以后发布线下作业直接选，不用重复上传（单个文件 ≤30MB）。</p>
        <div class="shelf-actions">
          <button type="button" class="btn small secondary inline-icon" :disabled="uploadingWb" @click="wbFileRef?.click()">
            <AppIcon name="plus" :size="14" /> {{ uploadingWb ? '上传中…' : '上传练习册 PDF' }}
          </button>
          <a
            v-if="selectedWorkbook"
            class="btn small secondary inline-icon"
            :href="selectedWorkbook.file_url"
            target="_blank"
            rel="noopener"
          >
            <AppIcon name="file" :size="14" /> 查看已选 PDF
          </a>
          <button
            v-if="selectedWorkbook"
            type="button"
            class="btn small danger-outline"
            @click="removeWorkbook"
          >
            {{ confirmDeleteWb ? '确认删除这本？' : '删除已选这本' }}
          </button>
        </div>
      </div>
    </div>

    <div class="card" :class="{ 'picker-open': subjectPickerOpen }">
      <h3>基本信息</h3>
      <div class="form-row">
        <label for="assignment-title">作业标题 <span class="required-mark">必填</span></label>
        <input
          id="assignment-title"
          ref="titleInputRef"
          v-model="title"
          type="text"
          required
          :aria-invalid="showRequiredHints && !title.trim() ? 'true' : undefined"
          :aria-describedby="showRequiredHints && !title.trim() ? 'assignment-title-error' : undefined"
          :placeholder="mode === 'offline' ? `例如：练习册 P12-14 ${subjectLabel}练习` : `例如：第二周${subjectLabel}作业`"
          maxlength="128"
        />
        <p v-if="showRequiredHints && !title.trim()" id="assignment-title-error" class="field-required-error" role="alert">请填写作业标题。</p>
      </div>
      <!-- v0.13.4：学科 / 总分 / 时间限制并到同一行；时间限制点开是自制日历面板，
           「允许学生修改」收在面板里（见下方 time-panel）；作业说明是独立折叠按钮 -->
      <div class="grid-3">
        <div class="form-row">
          <span id="assignment-subject-label" class="subject-field-label">学科</span>
          <div ref="subjectPickerRef" class="subject-picker">
            <button
              id="assignment-subject" ref="subjectPickerButtonRef" type="button" class="subject-select"
              aria-controls="assignment-subject-menu" aria-labelledby="assignment-subject-label assignment-subject-current"
              :aria-expanded="subjectPickerOpen" @click="toggleSubjectPicker"
            >
              <span id="assignment-subject-current">{{ subjectLabel }}</span>
              <AppIcon name="chevron-down" :size="16" class="picker-chevron" :class="{ open: subjectPickerOpen }" aria-hidden="true" />
            </button>
            <div v-if="subjectPickerOpen" id="assignment-subject-menu" class="subject-menu" role="radiogroup" aria-labelledby="assignment-subject-label">
              <label v-for="option in availableSubjectOptions" :key="option.value" class="subject-option" :class="{ 'is-selected': subject === option.value }">
                <input v-model="subject" type="radio" name="assignment-subject" :value="option.value" @change="subjectPickerOpen = false" />
                <span>{{ option.label }}</span>
              </label>
            </div>
          </div>
        </div>
        <div class="form-row">
          <label>作业总分（满分）</label>
          <div class="score-input-row">
            <input v-model.number="totalScore" type="number" min="1" max="10000" step="1" class="score-input" />
            <span class="hint">分 · 按步骤对错打分，待审核里可改分</span>
          </div>
        </div>
        <div class="form-row">
          <label>时间限制（选填）</label>
          <button type="button" class="time-field" :aria-expanded="timeOpen" @click="toggleTime">
            <AppIcon name="calendar" :size="16" />
            <span class="time-field-text">{{ deadline ? deadlineText : '不设截止，点此设置' }}</span>
            <AppIcon :name="timeOpen ? 'chevron-down' : 'chevron-right'" :size="15" />
          </button>
        </div>
      </div>
      <!-- v0.13.4：时间限制面板——自制日历选日 + 时分选择（不用系统自带日期框，
           外面只显示「10月15日 周三 22:00 截止」这样的友好文案）；
           「允许学生修改」收在这个面板里（作业说明已于 v0.13.5 拎出为独立折叠按钮） -->
      <div v-if="timeOpen" class="time-panel">
        <div class="time-grid">
          <div class="cal">
            <div class="cal-head">
              <button type="button" class="cal-nav" aria-label="上个月" title="上个月" @click="shiftMonth(-1)"><AppIcon name="chevron-left" :size="15" /></button>
              <span class="cal-title">{{ calCursor.y }}年{{ calCursor.m + 1 }}月</span>
              <button type="button" class="cal-nav" aria-label="下个月" title="下个月" @click="shiftMonth(1)"><AppIcon name="chevron-right" :size="15" /></button>
            </div>
            <div class="cal-week"><span v-for="w in ['一', '二', '三', '四', '五', '六', '日']" :key="w">{{ w }}</span></div>
            <div class="cal-days">
              <button
                v-for="(c, i) in calCells"
                :key="i"
                type="button"
                class="cal-day"
                :class="{ blank: !c.day, today: c.isToday, sel: !!c.dateStr && c.dateStr === selDate }"
                :disabled="!c.day || c.disabled"
                @click="c.day && pickDay(c.dateStr)"
              >{{ c.day || '' }}</button>
            </div>
            <p class="hint" style="margin-top: 8px">截止日期不能早于今天，过去的日期已置灰。</p>
          </div>
          <div class="time-side">
            <div class="form-row">
              <label>截止时刻</label>
              <div class="time-pick-row">
                <select v-model.number="selHour" @change="composeDeadline">
                  <option v-for="h in 24" :key="h - 1" :value="h - 1">{{ pad2(h - 1) }} 时</option>
                </select>
                <span class="time-colon">:</span>
                <select v-model.number="selMinute" @change="composeDeadline">
                  <option v-for="m in minuteOptions" :key="m" :value="m">{{ pad2(m) }} 分</option>
                </select>
                <button type="button" class="btn small secondary" :disabled="!deadline" @click="clearDeadline">清除截止</button>
              </div>
              <div class="quick-row">
                <button type="button" class="quick-chip" @click="quickPick(0)">今天 22:00</button>
                <button type="button" class="quick-chip" @click="quickPick(1)">明天 22:00</button>
                <button type="button" class="quick-chip" @click="quickPick(3)">三天后 22:00</button>
                <button type="button" class="quick-chip" @click="quickPick(7)">一周后 22:00</button>
              </div>
              <p v-if="deadline && deadlinePast" class="deadline-warn">这个时刻已经过了，发布会被拦下，请选晚一点的时间。</p>
              <p v-else-if="deadline" class="hint" style="margin-top: 8px">已设：{{ deadlineText }}</p>
            </div>
            <div class="form-row">
              <label>提交规则</label>
              <label class="revision-check">
                <input type="checkbox" v-model="allowRevision" />
                <span>允许学生在截止前修改已提交的作答</span>
              </label>
              <!-- v0.13.6：这段小字一直显示（此前只在勾选后才出现，老师没勾时看不到区别） -->
              <p class="hint" style="margin-top: 6px; line-height: 1.6">勾选后：截止前可反复修改，AI 先不批改，到截止时间按每题最后一次提交统一批改（请同时设置截止时间；没设截止则仍是立即批改）。不勾选：每道题只能交一次，交完立即批改。</p>
            </div>
          </div>
        </div>
      </div>
      <!-- v0.13.5：作业说明从时间面板里拎出来，恢复独立的折叠按钮（点开才出现，
           输入框随文案自动长高）；时间面板只管截止与允许修改 -->
      <div class="desc-row">
        <button type="button" class="btn small secondary inline-icon" :aria-expanded="descOpen" @click="toggleDesc">
          <AppIcon name="edit" :size="14" /> 作业说明（选填）
          <span v-if="description.trim()" class="opt-dot">已填</span>
          <AppIcon :name="descOpen ? 'chevron-down' : 'chevron-right'" :size="14" />
        </button>
      </div>
      <div v-if="descOpen" class="form-row desc-area">
        <textarea
          ref="descRef"
          v-model="description"
          rows="2"
          maxlength="2000"
          placeholder="例如：独立完成，写清每一步的依据；第 3 题可以用两种方法。"
          @input="growDesc"
        ></textarea>
        <p class="hint" style="margin-top: 6px">会显示在学生端交作业页顶部；写得越长，输入框会自动长高。</p>
      </div>
    </div>

    <div ref="classSectionRef" class="card" :class="{ 'picker-open': classPickerOpen }" tabindex="-1" role="group" aria-labelledby="assignment-classes-heading" :aria-required="true" :aria-invalid="showRequiredHints && !selectedClassIds.length ? 'true' : undefined" :aria-describedby="showRequiredHints && !selectedClassIds.length ? 'assignment-classes-error' : undefined">
      <h3 id="assignment-classes-heading">接收班级 <span class="required-mark">必选</span></h3>
      <p class="hint">只向所选班级发布；新建作业不会自动对其他班级学生开放。</p>
      <div v-if="classesForSubject.length" ref="classPickerRef" class="recipient-picker">
        <button
          ref="classPickerButtonRef" type="button" class="recipient-select"
          aria-controls="assignment-class-menu"
          :aria-expanded="classPickerOpen" :aria-invalid="showRequiredHints && !selectedClassIds.length ? 'true' : undefined"
          :aria-describedby="showRequiredHints && !selectedClassIds.length ? 'assignment-classes-error' : undefined"
          @click="toggleClassPicker"
        >
          <span v-if="selectedClassIds.length" class="recipient-selection">
            <span class="recipient-selection-name">{{ selectedClassSummary }}</span>
            <small>{{ selectedStudentCount }} 名学生</small>
          </span>
          <span v-else class="recipient-placeholder">请选择接收班级</span>
          <AppIcon name="chevron-down" :size="16" class="picker-chevron" :class="{ open: classPickerOpen }" aria-hidden="true" />
        </button>
        <div v-if="classPickerOpen" id="assignment-class-menu" class="recipient-menu" role="group" aria-label="可选接收班级">
          <label v-for="room in classesForSubject" :key="room.id" class="recipient-option" :class="{ 'is-selected': selectedClassIds.includes(room.id) }">
            <input v-model="selectedClassIds" type="checkbox" :value="room.id" />
            <span class="recipient-option-info"><b>{{ room.name }}</b><small>{{ room.student_count }} 名学生</small></span>
            <AppIcon v-if="selectedClassIds.includes(room.id)" name="check" :size="16" class="recipient-option-check" aria-hidden="true" />
          </label>
        </div>
      </div>
      <div v-else class="class-empty">
        还没有负责 {{ subjectLabel }} 的班级。<router-link to="/teacher/students">先到学生页建立班级</router-link>
      </div>
      <p v-if="showRequiredHints && !selectedClassIds.length" id="assignment-classes-error" class="field-required-error" role="alert">
        {{ classesForSubject.length ? '请选择至少一个接收班级。' : `当前没有可选班级，请先到学生页建立 ${subjectLabel} 班级。` }}
      </p>
    </div>

    <!-- 线下模式：拍照上传题目页，一次识别成一道草稿题 -->
    <div v-if="mode === 'offline'" class="card offline-photo-card">
      <h3><AppIcon name="camera" :size="18" /> 拍照上传题目页</h3>
      <p class="card-sub">把练习册上要做的题目拍下来，识别后会生成一道草稿题填到下方，检查修改后就能发布。多道题可以连拍多次。</p>
      <button class="btn inline-icon" :disabled="appendRecognizing" @click="pickPhotoAppend">
        <AppIcon name="camera" :size="16" /> {{ appendRecognizing ? '识别中…' : '拍一页题目页' }}
      </button>
    </div>

    <div v-for="(q, idx) in questions" :key="idx" class="card" :class="{ 'q-suspect': showResult(q) && q.check_status === 'suspect' }">
      <div class="q-head">
        <h3 style="margin-bottom: 0">第 {{ idx + 1 }} 题 · {{ subjectLabel }}</h3>
        <div class="q-actions">
          <button class="btn small secondary inline-icon" :disabled="q.recognizing" @click="pickPhoto(q)">
            <AppIcon name="camera" :size="15" /> {{ q.recognizing ? '识别中…' : '拍照识别题目' }}
          </button>
          <button class="btn small danger" @click="questions.splice(idx, 1)">删除本题</button>
        </div>
      </div>
      <p v-if="q.recognized" class="ok-msg" style="margin-bottom: 12px">已识别题目，请检查题干；标准步骤可按需展开修改。</p>
      <div class="form-row">
        <label>题干</label>
        <textarea v-model="q.prompt" rows="2" :placeholder="subject === 'math' ? '例如：解方程：3x-5=10' : '输入题目内容、要求或需要学生完成的任务'"></textarea>
      </div>
      <!-- v0.13.2：知识点 / 分值占比 / 参考答案并到同一行（AI 识别贴知识点右侧、
           AI 验算贴参考答案右侧），验算提示整行显示，下面整行留给标准解题步骤 -->
      <div class="grid-q-meta">
        <div class="form-row">
          <label>知识点（选填）</label>
          <div class="kp-row">
            <input v-model="q.knowledge_point" type="text" :placeholder="subject === 'math' ? '例如：一元一次方程' : `例如：${subjectLabel}核心知识点`" maxlength="64" />
            <button
              type="button"
              class="btn small secondary inline-icon"
              :disabled="q.kp_guessing || !q.prompt.trim()"
              :title="q.prompt.trim() ? '按题干用 AI 猜知识点' : '先填题干，再用 AI 识别'"
              @click="guessKp(q, `第 ${idx + 1} 题`)"
            >
              <AppIcon name="sparkles" :size="13" /> {{ q.kp_guessing ? '识别中…' : 'AI 识别' }}
            </button>
          </div>
        </div>
        <div class="form-row">
          <label>分值占比（占总分 %）</label>
          <div class="score-input-row">
            <input
              v-model.number="q.weight_pct"
              type="number" min="0" max="100" step="0.5"
              class="score-input" placeholder="均分"
            />
            <span class="hint">
              % · 满分约 {{ fmtScore(questionMax(q)) }} 分<template v-if="q.weight_pct === null || q.weight_pct === undefined">（留空均分）</template>
            </span>
          </div>
        </div>
        <div class="form-row">
            <label>{{ subject === 'math' ? '参考答案（选填）' : '参考答案或评分要点（选填）' }}</label>
          <div class="kp-row">
            <input v-model="q.reference_answer" type="text" :placeholder="subject === 'math' ? '例如：x=5' : '供视觉模型和教师批改参考'" />
            <button v-if="subject === 'math'"
              type="button"
              class="btn small secondary inline-icon"
              :disabled="q.check_status === 'checking' || !q.prompt.trim() || !q.reference_answer.trim()"
              :title="q.reference_answer.trim() ? '用 AI 验算参考答案' : '先填参考答案，再验算'"
              @click="checkOne(q)"
            >
              <AppIcon name="sparkles" :size="13" /> {{ q.check_status === 'checking' ? '验算中…' : 'AI 验算' }}
            </button>
          </div>
        </div>
      </div>
      <div v-if="subject === 'math' && (q.check_status === 'checking' || (showResult(q) && (q.check_status === 'ok' || q.check_status === 'suspect')))" class="check-notes">
        <p v-if="q.check_status === 'checking'" class="check-note muted">正在验算这道题的参考答案…</p>
        <p v-else-if="showResult(q) && q.check_status === 'ok'" class="check-note ok" :title="q.check_detail">
          <span class="check-ic"><AppIcon name="check" :size="13" /></span> AI 验算无误
        </p>
        <p v-else-if="showResult(q) && q.check_status === 'suspect'" class="check-note warn">
          <span class="check-ic"><AppIcon name="alert" :size="13" /></span>
          <span>参考答案可能有误：{{ q.check_detail }}（只是提醒，仍可照常发布）</span>
        </p>
      </div>
      <div v-if="!q.recognizing && q.stepsExpanded" class="form-row">
        <div class="steps-heading">
          <label>{{ subject === 'math' ? '标准解题步骤（选填，每行一步，含第一步原式，供批改参考）' : '参考作答要点（选填，每行一条，供视觉模型批改参考）' }}</label>
          <button type="button" class="btn ghost small inline-icon" @click="q.stepsExpanded = false">
            <AppIcon name="chevron-down" :size="14" class="steps-chevron-up" /> 收起
          </button>
        </div>
        <div v-if="subject === 'math'" class="symbol-bar" role="group" aria-label="数学符号">
          <button
            v-for="s in STEP_SYMBOLS"
            :key="s.label"
            type="button"
            class="symbol-btn"
            :title="`插入 ${s.label}`"
            @click="insertStepSymbol(q, s)"
          >{{ s.label }}</button>
        </div>
        <textarea :ref="(el) => setStepsRef(q, el)" v-model="q.standard_steps_text" rows="5" :placeholder="subject === 'math' ? mathStandardStepsPlaceholder : '按评分标准列出关键要点，每行一条'"></textarea>
        <p class="hint" style="margin-top: 8px">参考内容只提供给视觉模型和教师，不会展示给学生。</p>
      </div>
      <button
        v-else-if="!q.recognizing"
        type="button"
        class="btn ghost small inline-icon steps-toggle"
        @click="q.stepsExpanded = true"
      >
        <AppIcon name="chevron-down" :size="14" />
        {{ q.standard_steps_text.trim() ? '查看参考步骤' : subject === 'math' ? '添加标准解题步骤（选填）' : '添加参考作答要点（选填）' }}
      </button>
    </div>

    <!-- 大题（v0.13.1）：共享题干 + 若干小题，小题逐题作答/批改/计分 -->
    <div v-for="(g, gi) in groups" :key="`g${gi}`" class="card">
      <div class="q-head">
        <h3 style="margin-bottom: 0">大题 {{ gi + 1 }} · {{ subjectLabel }}</h3>
        <div class="q-actions">
          <button type="button" class="btn small secondary inline-icon" :disabled="groupRecognizing || g.diagramBusy" @click="pickGroupPhoto(g)">
            <AppIcon name="camera" :size="15" /> {{ groupRecognizing && groupPhotoTarget === g ? '识别中…' : '拍照识别大题' }}
          </button>
          <button type="button" class="btn small secondary inline-icon" :disabled="g.diagramBusy || g.diagramStarting || groupRecognizing || !groupFigurePrompt(g).trim()" @click="generateGroupFigure(g)">
            <AppIcon name="sparkles" :size="14" /> {{ g.diagramBusy ? '正在生成…' : g.diagram ? '重新生成图形' : 'AI生成图形' }}
          </button>
          <button type="button" class="btn small danger" @click="groups.splice(gi, 1)">删除大题</button>
        </div>
      </div>
      <div class="group-material" :class="{ 'has-figure': g.diagram }">
        <div class="form-row">
          <label>大题题干（共享材料，每道小题上方都会展示给学生）</label>
          <textarea v-model="g.stem" rows="3" :placeholder="subject === 'math' ? '例如：已知直角三角形的两条直角边分别为 3 和 4，回答下列问题。' : '填写多道小题共用的题干材料或背景信息'" @input="clearGroupFigure(g)"></textarea>
          <div v-if="g.diagramBusy" class="figure-progress" role="status">
            <span>图形生成中，可先发布作业</span>
            <IndeterminateProgress label="图形生成中" />
          </div>
          <p v-if="g.diagramMessage" class="hint figure-message" role="status">{{ g.diagramMessage }}</p>
        </div>
        <div v-if="g.diagram" class="figure-preview">
          <FigureRenderer :figure="g.diagram" />
          <button type="button" class="btn ghost small" :disabled="g.diagramBusy" @click="removeGroupFigure(g)">移除图形</button>
        </div>
      </div>
      <div v-for="(sub, si) in g.subs" :key="si" class="sub-block">
        <div class="q-head">
          <h4 style="margin: 0">小题（{{ si + 1 }}）</h4>
          <div class="q-actions">
            <!-- v0.13.11：小题卡不再单独拍照识别——识别入口在大题层级
                 （大题卡头的「拍照识别大题」一次拆出题干与全部小题） -->
            <button type="button" class="btn small danger" :disabled="g.subs.length === 1" @click="removeGroupSub(g, si)">删除小题</button>
          </div>
        </div>
        <p v-if="sub.recognized" class="ok-msg" style="margin-bottom: 12px">已识别题目，请检查题干；标准步骤可按需展开修改。</p>
        <div class="form-row">
          <label>小题题干</label>
          <textarea v-model="sub.prompt" rows="2" placeholder="例如：求斜边的长" @input="clearGroupFigure(g)"></textarea>
        </div>
        <!-- v0.13.2：与普通题同版式——知识点 / 分值占比 / 参考答案一行，步骤整行在下 -->
        <div class="grid-q-meta">
          <div class="form-row">
            <label>知识点（选填）</label>
            <div class="kp-row">
            <input v-model="sub.knowledge_point" type="text" :placeholder="subject === 'math' ? '例如：勾股定理' : `例如：${subjectLabel}核心知识点`" maxlength="64" />
              <button
                type="button"
                class="btn small secondary inline-icon"
                :disabled="sub.kp_guessing || !sub.prompt.trim()"
                :title="sub.prompt.trim() ? '按题干用 AI 猜知识点' : '先填题干，再用 AI 识别'"
                @click="guessKp(sub, `大题 ${gi + 1} 小题（${si + 1}）`)"
              >
                <AppIcon name="sparkles" :size="13" /> {{ sub.kp_guessing ? '识别中…' : 'AI 识别' }}
              </button>
            </div>
          </div>
          <div class="form-row">
            <label>分值占比（占总分 %）</label>
            <div class="score-input-row">
              <input
                v-model.number="sub.weight_pct"
                type="number" min="0" max="100" step="0.5"
                class="score-input" placeholder="均分"
              />
              <span class="hint">
                % · 满分约 {{ fmtScore(questionMax(sub)) }} 分<template v-if="sub.weight_pct === null || sub.weight_pct === undefined">（留空均分）</template>
              </span>
            </div>
          </div>
          <div class="form-row">
            <label>{{ subject === 'math' ? '参考答案（选填）' : '参考答案或评分要点（选填）' }}</label>
            <div class="kp-row">
              <input v-model="sub.reference_answer" type="text" :placeholder="subject === 'math' ? '例如：c=5' : '供视觉模型和教师批改参考'" />
              <button v-if="subject === 'math'"
                type="button"
                class="btn small secondary inline-icon"
                :disabled="sub.check_status === 'checking' || !sub.prompt.trim() || !sub.reference_answer.trim()"
                :title="sub.reference_answer.trim() ? '用 AI 验算参考答案' : '先填参考答案，再验算'"
                @click="checkOne(sub)"
              >
                <AppIcon name="sparkles" :size="13" /> {{ sub.check_status === 'checking' ? '验算中…' : 'AI 验算' }}
              </button>
            </div>
          </div>
        </div>
        <div v-if="subject === 'math' && (sub.check_status === 'checking' || (showResult(sub) && (sub.check_status === 'ok' || sub.check_status === 'suspect')))" class="check-notes">
          <p v-if="sub.check_status === 'checking'" class="check-note muted">正在验算这道题的参考答案…</p>
          <p v-else-if="showResult(sub) && sub.check_status === 'ok'" class="check-note ok" :title="sub.check_detail">
            <span class="check-ic"><AppIcon name="check" :size="13" /></span> AI 验算无误
          </p>
          <p v-else-if="showResult(sub) && sub.check_status === 'suspect'" class="check-note warn">
            <span class="check-ic"><AppIcon name="alert" :size="13" /></span>
            <span>参考答案可能有误：{{ sub.check_detail }}（只是提醒，仍可照常发布）</span>
          </p>
        </div>
        <div v-if="!(groupRecognizing && groupPhotoTarget === g) && sub.stepsExpanded" class="form-row">
          <div class="steps-heading">
            <label>{{ subject === 'math' ? '标准解题步骤（选填，每行一步）' : '参考作答要点（选填，每行一条）' }}</label>
            <button type="button" class="btn ghost small inline-icon" @click="sub.stepsExpanded = false">
              <AppIcon name="chevron-down" :size="14" class="steps-chevron-up" /> 收起
            </button>
          </div>
          <div v-if="subject === 'math'" class="symbol-bar" role="group" aria-label="数学符号">
            <button
              v-for="s in STEP_SYMBOLS"
              :key="s.label"
              type="button"
              class="symbol-btn"
              :title="`插入 ${s.label}`"
              @click="insertStepSymbol(sub, s)"
            >{{ s.label }}</button>
          </div>
          <textarea :ref="(el) => setStepsRef(sub, el)" v-model="sub.standard_steps_text" rows="5" :placeholder="subject === 'math' ? groupMathStandardStepsPlaceholder : '按评分标准列出关键要点，每行一条'"></textarea>
        </div>
        <button
          v-else-if="!(groupRecognizing && groupPhotoTarget === g)"
          type="button"
          class="btn ghost small inline-icon steps-toggle"
          @click="sub.stepsExpanded = true"
        >
          <AppIcon name="chevron-down" :size="14" />
          {{ sub.standard_steps_text.trim() ? '查看参考步骤' : subject === 'math' ? '添加标准解题步骤（选填）' : '添加参考作答要点（选填）' }}
        </button>
      </div>
      <button type="button" class="btn secondary small inline-icon" @click="g.subs.push(blankQuestion())">
        <AppIcon name="plus" :size="14" /> 添加小题
      </button>
    </div>

    <input ref="photoRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onPhotoChange" />
    <input ref="groupPhotoRef" type="file" accept="image/jpeg,image/png,image/webp" hidden @change="onGroupPhotoChange" />
    <!-- 分值占比合计（评分系统）：只统计会真正发布的题（题干或知识点已填）；
         v0.13.9：一道题都还没加时不显示这条，避免空着就报「还差 100%」 -->
    <div v-if="questions.length || groups.length" class="card weight-bar">
      <span class="weight-sum" :class="{ bad: !weightSumOk }">
        分值占比合计 <b class="tnum">{{ fmtScore(weightSum) }}%</b>
        <template v-if="weightSumOk">，正好 100%</template>
        <template v-else-if="weightSum < 100">，还差 {{ fmtScore(100 - weightSum) }}%</template>
        <template v-else>，超出了 {{ fmtScore(weightSum - 100) }}%</template>
      </span>
      <span class="hint">没填占比的题按「100 ÷ 题数」计入合计；合计不是 100% 时不能发布，避免各题满分加起来超过总分。</span>
      <button type="button" class="btn small secondary" @click="distributeEvenly">一键均分</button>
    </div>
    <div class="toolbar publish-actions">
      <div v-if="recognitionInProgress" class="recognition-progress-status" role="status" aria-live="polite">
        <span>正在识别题目，请稍候</span>
        <div class="recognition-progress-track" role="progressbar" aria-label="正在识别题目">
          <span class="recognition-progress-indicator"></span>
        </div>
      </div>
      <button type="button" class="btn secondary inline-icon" @click="addQuestion"><AppIcon name="plus" :size="15" /> 添加小题</button>
      <button type="button" class="btn secondary inline-icon" @click="addGroup"><AppIcon name="plus" :size="15" /> 添加大题</button>
      <button type="button" class="btn secondary inline-icon" :disabled="groupRecognizing" @click="pickGroupPhoto()"><AppIcon name="camera" :size="15" /> {{ groupRecognizing && !groupPhotoTarget ? '识别中…' : '拍照识别大题' }}</button>
      <span v-if="recognitionError" class="recognition-error" role="alert">
        <AppIcon name="alert" :size="14" /> {{ recognitionError }}
      </span>
      <span v-if="questions.length || groups.length" class="weight-mini" :class="{ bad: !weightSumOk }">分值占比合计 <b class="tnum">{{ fmtScore(weightSum) }}%</b><template v-if="!weightSumOk">（需 100%）</template></span>
      <span class="spacer"></span>
      <button class="btn" :disabled="submitting || checkingAll || groups.some(g => g.diagramStarting)" @click="submit">
        {{ checkingAll ? '正在验算参考答案…' : submitting ? '发布中…' : mode === 'offline' ? '发布线下作业' : '发布作业' }}
      </button>
    </div>
    </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import api from '../../api/client'
import { useTeacherStore } from '../../stores/teacher'
import type { Classroom, FigureSpec, QuestionSubject, SubjectAgentCode, TeacherAssignment, TeacherAssignmentDraftSeed, TeacherAssignmentInput, Workbook } from '../../api/types'
import { useAuthStore } from '../../stores/auth'
import AppIcon from '../../components/icons/AppIcon.vue'
import FigureRenderer from '../../components/FigureRenderer.vue'
import IndeterminateProgress from '../../components/IndeterminateProgress.vue'
import PublishModeCards from '../../components/PublishModeCards.vue'
import { formatRecognizedMath } from '../../utils/recognizedMath'
import { SUBJECT_OPTIONS } from '../../utils/subjectLabels'

const props = withDefaults(defineProps<{
  embedded?: boolean
  chatWorkflow?: boolean
  initialDraft?: TeacherAssignmentDraftSeed
}>(), { embedded: false, chatWorkflow: false })
const emit = defineEmits<{ published: [assignment: TeacherAssignment] }>()
const chatWorkflowCollapsed = ref(false)

const teacher = useTeacherStore()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

interface QuestionForm {
  prompt: string
  knowledge_point: string
  standard_steps_text: string
  stepsExpanded: boolean
  reference_answer: string
  weight_pct: number | null   // 评分系统：分值占比 %；null = 留空（按题数均分）
  recognized: boolean   // 是否刚通过照片识别填入（展示检查提示）
  recognizing: boolean  // 识别请求进行中
  kp_guessing: boolean  // 知识点 AI 识别进行中（v0.13.0）
  // 参考答案 AI 验算（v0.9.3）：check_stamp 是验算时「题干+答案」的指纹，
  // 老师改了题干或答案后指纹对不上，旧验算标记自动不显示
  check_status: 'idle' | 'checking' | 'ok' | 'suspect' | 'unknown'
  check_detail: string
  check_stamp: string
}

const requestedMode = !props.chatWorkflow && (route.query.mode === 'online' || route.query.mode === 'offline') ? route.query.mode : null
const mode = ref<'online' | 'offline'>(requestedMode ?? 'online')
// 两级导航（v0.12.0）：choose = 选发布方式；form = 填发布表单。两级同组件，
// 返回上一级不清空已填内容；选方式时把 mode 写进 query，刷新/书架深链直达表单级。
const step = ref<'choose' | 'form'>(props.chatWorkflow || requestedMode ? 'form' : 'choose')

function chooseMode(m: 'online' | 'offline') {
  mode.value = m
  step.value = 'form'
  router.replace({ query: { ...route.query, mode: m } })
  // v0.13.6：不再 scrollTo(0)——点卡时页面停在原地，顶部标题位置一点都不动
}

const title = ref(props.initialDraft?.title ?? '')
const titleInputRef = ref<HTMLInputElement | null>(null)
const description = ref('')   // 作业说明（v0.13.1）：两种模式共用，学生端交作业页顶部展示
const mathStandardStepsPlaceholder = '3x-5=10\n3x=10+5\n3x=15\nx=5'
const groupMathStandardStepsPlaceholder = 'c²=a²+b²\nc²=3²+4²\nc²=25\nc=5'
const subject = ref<QuestionSubject>((auth.activeSubject as QuestionSubject) || 'math')
const availableSubjectOptions = computed(() => SUBJECT_OPTIONS.filter(
  (option) => option.value === (auth.activeSubject || 'math'),
))
const subjectPickerOpen = ref(false)
const subjectPickerRef = ref<HTMLElement | null>(null)
const subjectPickerButtonRef = ref<HTMLButtonElement | null>(null)
const classrooms = ref<Classroom[]>([])
const selectedClassIds = ref<number[]>([])
const classSectionRef = ref<HTMLElement | null>(null)
const classPickerOpen = ref(false)
const classPickerRef = ref<HTMLElement | null>(null)
const classPickerButtonRef = ref<HTMLButtonElement | null>(null)
const classesForSubject = computed(() => classrooms.value.filter(
  (room) => room.subjects.includes(subject.value as SubjectAgentCode),
))
const selectedClassrooms = computed(() => classesForSubject.value.filter((room) => selectedClassIds.value.includes(room.id)))
const selectedClassSummary = computed(() => {
  const selected = selectedClassrooms.value
  if (selected.length < 2) return selected[0]?.name ?? ''
  if (selected.length === 2) return selected.map((room) => room.name).join('、')
  return `${selected[0].name} 等 ${selected.length} 个班级`
})
const selectedStudentCount = computed(() => selectedClassrooms.value.reduce(
  (total, room) => total + Math.max(0, Number(room.student_count) || 0), 0,
))
function toggleSubjectPicker() {
  classPickerOpen.value = false
  subjectPickerOpen.value = !subjectPickerOpen.value
}
function toggleClassPicker() {
  subjectPickerOpen.value = false
  classPickerOpen.value = !classPickerOpen.value
}
function onAssignmentPickerDocumentClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof Node)) return
  if (!subjectPickerRef.value?.contains(target)) subjectPickerOpen.value = false
  if (!classPickerRef.value?.contains(target)) classPickerOpen.value = false
}
function onAssignmentPickerDocumentKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (classPickerOpen.value) {
    classPickerOpen.value = false
    classPickerButtonRef.value?.focus()
  } else if (subjectPickerOpen.value) {
    subjectPickerOpen.value = false
    subjectPickerButtonRef.value?.focus()
  } else return
  event.preventDefault()
  event.stopPropagation()
}
onMounted(() => {
  document.addEventListener('click', onAssignmentPickerDocumentClick)
  document.addEventListener('keydown', onAssignmentPickerDocumentKeydown)
})
watch(subject, () => {
  selectedClassIds.value = []
  classPickerOpen.value = false
})
const subjectLabel = computed(() => SUBJECT_OPTIONS.find((option) => option.value === subject.value)?.label ?? '其他')
const totalScore = ref(100)   // 评分系统：作业总分（满分），默认 100
const blankQuestion = (): QuestionForm => ({
  prompt: '', knowledge_point: '', standard_steps_text: '', stepsExpanded: true, reference_answer: '',
  weight_pct: null,
  recognized: false, recognizing: false, kp_guessing: false,
  check_status: 'idle', check_detail: '', check_stamp: ''
})
// v0.13.9：进表单时一道题都不给——老师先选「添加小题」或「添加大题」，
// 避免一进来就摆一道空题、还得先删
const questions = ref<QuestionForm[]>(props.initialDraft?.questions.map((draft) => ({
  ...blankQuestion(),
  prompt: formatRecognizedMath(draft.prompt),
  standard_steps_text: formatRecognizedMath(draft.standard_steps?.join('\n') ?? ''),
  recognized: true,
})) ?? [])
// v0.13.1：允许修改开关 + 大题/小题（大题 = 共享题干 + 若干小题，小题仍是普通题目）
const allowRevision = ref(false)
interface GroupForm {
  stem: string
  subs: QuestionForm[]
  diagram: FigureSpec | null
  diagramBusy: boolean
  diagramStarting: boolean
  diagramJobId: number | null
  diagramSubject: string
  diagramPrompt: string
  diagramMessage: string
}
const groups = ref<GroupForm[]>([])
const blankGroup = (): GroupForm => ({ stem: '', subs: [blankQuestion()], diagram: null, diagramBusy: false, diagramStarting: false, diagramJobId: null, diagramSubject: '', diagramPrompt: '', diagramMessage: '' })
function addGroup() {
  groups.value.push(blankGroup())
}

function groupFigurePrompt(g: GroupForm): string {
  return [g.stem.trim(), ...g.subs.map((item) => item.prompt.trim())].filter(Boolean).join('\n')
}
function clearGroupFigure(g: GroupForm) {
  const hadFigure = !!g.diagram || g.diagramBusy
  g.diagramJobId = null
  g.diagramBusy = false
  g.diagram = null
  g.diagramMessage = hadFigure ? '题目内容已修改，请重新生成图形。' : ''
}
watch(subject, () => { groups.value.forEach(clearGroupFigure) })
function removeGroupFigure(g: GroupForm) {
  g.diagram = null
  g.diagramJobId = null
  g.diagramMessage = ''
}
function removeGroupSub(g: GroupForm, index: number) {
  g.subs.splice(index, 1)
  clearGroupFigure(g)
}
let figurePageActive = true
onBeforeUnmount(() => {
  figurePageActive = false
  document.removeEventListener('click', onAssignmentPickerDocumentClick)
  document.removeEventListener('keydown', onAssignmentPickerDocumentKeydown)
})
interface FigureJob { id: number; status: string; figure: FigureSpec | null; message: string }
async function generateGroupFigure(g: GroupForm) {
  const questionText = groupFigurePrompt(g)
  const jobSubject = subject.value
  if (!questionText) return
  g.diagram = null
  g.diagramJobId = null
  g.diagramBusy = true
  g.diagramStarting = true
  g.diagramPrompt = questionText
  g.diagramSubject = jobSubject
  g.diagramMessage = ''
  try {
    const { data: job } = await api.post<FigureJob>('/api/teacher/diagrams/jobs', { subject: jobSubject, question_text: questionText })
    g.diagramStarting = false
    if (groupFigurePrompt(g) !== questionText || subject.value !== jobSubject) { g.diagramBusy = false; return }
    g.diagramJobId = job.id
    while (figurePageActive && g.diagramJobId === job.id) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000))
      if (!figurePageActive || g.diagramJobId !== job.id) return
      const { data } = await api.get<FigureJob>(`/api/teacher/diagrams/jobs/${job.id}`)
      if (groupFigurePrompt(g) !== questionText || subject.value !== jobSubject) {
        clearGroupFigure(g)
        return
      }
      if (data.status === 'completed' || data.status === 'failed') {
        g.diagram = data.figure
        g.diagramMessage = data.figure ? '' : (data.message || '题目中没有需要补充的图形。')
        g.diagramBusy = false
        return
      }
    }
  } catch (err: unknown) {
    g.diagramMessage = '图形任务查询失败：' + errMsg(err, '请稍后重试。')
    g.diagramBusy = false
  } finally {
    g.diagramStarting = false
  }
}

// ---------- v0.13.4：时间限制面板（自制日历 + 时分）/ 备注自适应高度 ----------
// deadline 仍存 'YYYY-MM-DDTHH:mm' 字符串（提交与校验口径不变），只是录入换成
// 自制日历、展示换成友好文案，不再露系统日期框的 yyyy 占位格式。
const descRef = ref<HTMLTextAreaElement | null>(null)
/** 作业说明输入框随文案变长自动长高（上限后内部滚动，避免无限撑长页面） */
function growDesc() {
  const ta = descRef.value
  if (!ta) return
  ta.style.height = 'auto'
  ta.style.height = `${Math.min(ta.scrollHeight + 2, 242)}px`
}
const descOpen = ref(false)   // v0.13.5：作业说明独立折叠按钮（已从时间面板拎出）
function toggleDesc() {
  descOpen.value = !descOpen.value
  if (descOpen.value) void nextTick(growDesc)
}
const pad2 = (n: number) => String(n).padStart(2, '0')
const timeOpen = ref(false)
const selHour = ref(22)
const selMinute = ref(0)
const calCursor = ref<{ y: number; m: number }>({ y: new Date().getFullYear(), m: new Date().getMonth() })
/** 已选日期（deadline 的日期部分）；没设截止为空串 */
const selDate = computed(() => (deadline.value ? deadline.value.slice(0, 10) : ''))
const minuteOptions = computed(() => {
  const base = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
  return base.includes(selMinute.value) ? base : [...base, selMinute.value].sort((a, b) => a - b)
})
function composeDeadline() {
  if (!selDate.value) return
  deadline.value = `${selDate.value}T${pad2(selHour.value)}:${pad2(selMinute.value)}`
}
function toggleTime() {
  timeOpen.value = !timeOpen.value
  if (timeOpen.value) {
    if (deadline.value) {
      const d = new Date(deadline.value)
      if (!Number.isNaN(d.getTime())) {
        calCursor.value = { y: d.getFullYear(), m: d.getMonth() }
        selHour.value = d.getHours()
        selMinute.value = d.getMinutes()
      }
    }
    void nextTick(growDesc)
  }
}
function shiftMonth(delta: number) {
  const d = new Date(calCursor.value.y, calCursor.value.m + delta, 1)
  calCursor.value = { y: d.getFullYear(), m: d.getMonth() }
}
interface CalCell { day: number; dateStr: string; disabled: boolean; isToday: boolean }
const calCells = computed<CalCell[]>(() => {
  const { y, m } = calCursor.value
  const lead = (new Date(y, m, 1).getDay() + 6) % 7 // 周一起头：月初前面空几格
  const days = new Date(y, m + 1, 0).getDate()
  const now = new Date()
  const todayStr = `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`
  const cells: CalCell[] = []
  for (let i = 0; i < lead; i++) cells.push({ day: 0, dateStr: '', disabled: true, isToday: false })
  for (let d = 1; d <= days; d++) {
    const ds = `${y}-${pad2(m + 1)}-${pad2(d)}`
    cells.push({ day: d, dateStr: ds, disabled: ds < todayStr, isToday: ds === todayStr })
  }
  return cells
})
function pickDay(dateStr: string) {
  deadline.value = `${dateStr}T${pad2(selHour.value)}:${pad2(selMinute.value)}`
}
function quickPick(daysFromToday: number) {
  const d = new Date()
  d.setDate(d.getDate() + daysFromToday)
  selHour.value = 22
  selMinute.value = 0
  calCursor.value = { y: d.getFullYear(), m: d.getMonth() }
  deadline.value = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T22:00`
}
function clearDeadline() {
  deadline.value = ''
}
/** 设好的截止是否已经过去（面板里即时提醒；发布时 submit 还会再拦一次） */
const deadlinePast = computed(() => !!deadline.value && new Date(deadline.value).getTime() <= Date.now())
/** 字段上显示的友好时间，如「10月15日 周三 22:00 截止」 */
const deadlineText = computed(() => {
  if (!deadline.value) return ''
  const d = new Date(deadline.value)
  if (Number.isNaN(d.getTime())) return ''
  const wk = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()]
  const yPart = d.getFullYear() !== new Date().getFullYear() ? `${d.getFullYear()}年` : ''
  return `${yPart}${d.getMonth() + 1}月${d.getDate()}日 ${wk} ${pad2(d.getHours())}:${pad2(d.getMinutes())} 截止`
})
/** 全部题目表单（普通题 + 各大题的小题），校验/分值口径统一走这份名单 */
const allForms = computed(() => [...questions.value, ...groups.value.flatMap((g) => g.subs)])
const submitting = ref(false)
const checkingAll = ref(false)  // 发布前批量验算进行中（v0.9.3）
const error = ref('')
const recognitionError = ref('')
const showRequiredHints = ref(false)
const ok = ref(false)

// v0.13.11：红色警示是顶部悬浮 toast，出现 5 秒后自动消失；连续报错重新计时
let errorTimer: ReturnType<typeof setTimeout> | undefined
watch(error, (v) => {
  if (errorTimer) clearTimeout(errorTimer)
  if (v) errorTimer = setTimeout(() => { error.value = '' }, 5000)
})

function errMsg(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return typeof d === 'string' ? d : fallback
}

function recognitionFailureMessage(e: unknown, fallback: string): string {
  const cause = e as {
    code?: string
    message?: string
    request?: unknown
    response?: { status?: number; data?: { detail?: unknown } }
  }
  const detail = cause?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (cause?.code === 'ECONNABORTED' || cause?.code === 'ETIMEDOUT') {
    return '识别请求超时，请检查网络后重试。'
  }
  if (cause?.code === 'ERR_NETWORK' || (!cause?.response && (cause?.request || cause?.message === 'Network Error'))) {
    return '网络连接失败，识别未完成，请检查网络后重试。'
  }
  const status = cause?.response?.status
  if (typeof status === 'number' && status >= 500) {
    return '识别服务暂时不可用，请稍后重试。'
  }
  return fallback
}

function addQuestion() {
  questions.value.push(blankQuestion())
}

// ---------- 评分系统：分值占比合计与校验 ----------
// 口径与后端一致：没填占比的题按「100 ÷ 会真正发布的题数」均分。
// 合计必须 = 100%（容差 0.5），否则各题满分加起来会超过/不足作业总分，发布拦截。

function fmtScore(v: number): string {
  return String(Math.round(v * 10) / 10)
}

/** 会真正发布的题目（题干或知识点已填），与 submit 的 valid 口径一致（含大题小题） */
const inPlayQuestions = computed(() =>
  allForms.value.filter((q) => q.prompt.trim() || q.knowledge_point.trim())
)

function effectivePct(q: QuestionForm, n: number): number {
  const v = q.weight_pct
  if (v === null || v === undefined || Number.isNaN(Number(v))) return n ? 100 / n : 0
  return Number(v)
}

/** 本题满分（按生效占比折算），供题行内实时展示 */
function questionMax(q: QuestionForm): number {
  const n = inPlayQuestions.value.length || questions.value.length || 1
  return ((Number(totalScore.value) || 0) * effectivePct(q, n)) / 100
}

const weightSum = computed(() => {
  const list = inPlayQuestions.value
  if (!list.length) return 0
  const n = list.length
  return list.reduce((s, q) => s + effectivePct(q, n), 0)
})
const weightSumOk = computed(() => Math.abs(weightSum.value - 100) <= 0.5)

/** 一键均分：把 100% 平均写进每道会发布的题（最后一题吃掉小数尾差，合计恰好 100） */
function distributeEvenly() {
  const list = inPlayQuestions.value.length ? inPlayQuestions.value : allForms.value
  const n = list.length
  if (!n) return
  const base = Math.floor((100 / n) * 10) / 10
  list.forEach((q, i) => {
    q.weight_pct = i === n - 1 ? Math.round((100 - base * (n - 1)) * 10) / 10 : base
  })
}

// ---------- 参考答案 AI 验算（v0.9.3）：只提醒、永不拦截发布 ----------

interface AnswerCheckResult {
  status: 'ok' | 'suspect' | 'unknown'
  detail: string
  method: 'sympy' | 'llm' | 'none'
}

/** 验算指纹：题干、知识点或参考答案变化后，旧结果视为过期、不再显示 */
function stampOf(q: QuestionForm): string {
  return `${q.prompt.trim()}\n${q.knowledge_point.trim()}\n${q.reference_answer.trim()}`
}

function answerCheckStampOf(q: QuestionForm): string {
  return `${q.prompt.trim()}\n${q.reference_answer.trim()}`
}

const inFlightAnswerChecks = new WeakMap<QuestionForm, { stamp: string; promise: Promise<void> }>()
const ANSWER_CHECK_CONCURRENCY = 4
let activeAnswerChecks = 0
const answerCheckWaiters: Array<() => void> = []

// 手动逐题验算与发布前批量验算共用并发槽位，避免单页同时打满验算接口。
async function acquireAnswerCheckSlot(): Promise<void> {
  if (activeAnswerChecks < ANSWER_CHECK_CONCURRENCY) {
    activeAnswerChecks += 1
    return
  }
  await new Promise<void>((resolve) => answerCheckWaiters.push(resolve))
}

function releaseAnswerCheckSlot() {
  const next = answerCheckWaiters.shift()
  if (next) next()
  else activeAnswerChecks -= 1
}

function showResult(q: QuestionForm): boolean {
  return q.check_stamp !== '' && q.check_stamp === stampOf(q)
}

function runCheck(q: QuestionForm): Promise<void> {
  const stamp = stampOf(q)
  const existing = inFlightAnswerChecks.get(q)
  if (existing?.stamp === stamp) return existing.promise

  const stem = q.prompt.trim()
  const referenceAnswer = q.reference_answer.trim()
  const knowledgePoint = q.knowledge_point.trim()
  q.check_stamp = stamp
  q.check_status = 'checking'
  q.check_detail = ''
  const request = Promise.resolve().then(async () => {
    let acquiredSlot = false
    try {
      await acquireAnswerCheckSlot()
      acquiredSlot = true
      if (stampOf(q) !== stamp) return
      const { data } = await api.post<AnswerCheckResult>('/api/teacher/questions/check-answer', {
        stem,
        reference_answer: referenceAnswer,
        knowledge_point: knowledgePoint || undefined
      })
      if (stampOf(q) !== stamp) return
      q.check_status = data.status
      q.check_detail = data.detail
    } catch (e) {
      // 验算接口异常按 unknown 处理：不显示任何标记，更不能挡住发布
      if (stampOf(q) === stamp) {
        q.check_status = 'unknown'
        q.check_detail = ''
      }
      console.error(e)
    } finally {
      if (acquiredSlot) releaseAnswerCheckSlot()
      if (inFlightAnswerChecks.get(q)?.promise === request) {
        inFlightAnswerChecks.delete(q)
      }
      if (q.check_stamp === stamp && stampOf(q) !== stamp && q.check_status === 'checking') {
        q.check_status = 'idle'
        q.check_detail = ''
      }
    }
  })
  inFlightAnswerChecks.set(q, { stamp, promise: request })
  return request
}

async function checkOne(q: QuestionForm) {
  if (q) await runCheck(q)
}

// ---------- 知识点 AI 识别（v0.13.0）：文本模型按题干猜知识点，结果可改 ----------
async function guessKp(q: QuestionForm, label: string) {
  if (!q || q.kp_guessing || !q.prompt.trim()) return
  q.kp_guessing = true
  try {
    const { data } = await api.post<{ knowledge_point: string }>(
      '/api/teacher/questions/guess-knowledge-point',
      { prompt: q.prompt.trim() }
    )
    if (data.knowledge_point) {
      q.knowledge_point = data.knowledge_point
    } else {
      error.value = `${label}：AI 没能判断出知识点，请手动填写。`
    }
  } catch (err) {
    error.value = `${label}知识点识别失败：` + errMsg(err, '请稍后重试或手动填写。')
    console.error(err)
  } finally {
    q.kp_guessing = false
  }
}

// ---------- 标准解题步骤做题板（v0.13.1）：符号栏与学生端同款，插入光标处 ----------
// 只放后端解析器认得的符号；√ 插入成 √( 光标落在括号里
interface StepSymbol { label: string; text: string; caretBack?: number }
const STEP_SYMBOLS: StepSymbol[] = [
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
const stepsRefs = new Map<QuestionForm, HTMLTextAreaElement>()
function setStepsRef(q: QuestionForm, el: unknown) {
  if (el) stepsRefs.set(q, el as HTMLTextAreaElement)
  else stepsRefs.delete(q)
}
function insertStepSymbol(q: QuestionForm, s: StepSymbol) {
  const ta = stepsRefs.get(q)
  const cur = q.standard_steps_text
  const start = ta ? ta.selectionStart : cur.length
  const end = ta ? ta.selectionEnd : cur.length
  q.standard_steps_text = cur.slice(0, start) + s.text + cur.slice(end)
  void nextTick(() => {
    if (!ta) return
    ta.focus()
    const pos = start + s.text.length - (s.caretBack ?? 0)
    ta.setSelectionRange(pos, pos)
  })
}

// ---------- 练习册知识库（v0.5.0） ----------
const workbooks = ref<Workbook[]>([])
const workbookId = ref<number | ''>('')
const shelfOpen = ref(false)   // v0.13.3：书架选书面板开关（书本只在面板里陈列）
const wbOpen = ref(false)      // v0.13.4：「练习册与范围」整卡折叠开关，默认收起
/** 折叠标题行上的已选摘要：一眼看出选了哪本、填了什么范围 */
const wbSummary = computed(() =>
  selectedWorkbook.value
    ? `${selectedWorkbook.value.title}${pageRange.value.trim() ? ` · ${pageRange.value.trim()}` : ''}`
    : '还没选练习册，点开选择'
)

/** 书架里点选一本：选中即关面板，按钮上回显书名 */
function pickWorkbook(w: Workbook) {
  workbookId.value = w.id
  confirmDeleteWb.value = false
  shelfOpen.value = false
}
const pageRange = ref('')
const deadline = ref('')
const wbFileRef = ref<HTMLInputElement | null>(null)
const uploadingWb = ref(false)
const confirmDeleteWb = ref(false)

const selectedWorkbook = computed(() => workbooks.value.find((w) => w.id === Number(workbookId.value)) ?? null)

async function loadWorkbooks() {
  try {
    workbooks.value = await teacher.fetchWorkbooks()
  } catch (e) {
    console.error(e)
  }
}

async function onWorkbookFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    error.value = '练习册只支持 PDF 文件。'
    return
  }
  if (file.size > 30 * 1024 * 1024) {
    error.value = 'PDF 太大了（超过 30MB），请压缩后再传。'
    return
  }
  uploadingWb.value = true
  error.value = ''
  try {
    const wb = await teacher.uploadWorkbook(file)
    workbooks.value.unshift(wb)
    workbookId.value = wb.id
    confirmDeleteWb.value = false
    shelfOpen.value = false // 上传成功即选中并关掉书架面板
  } catch (err) {
    error.value = '练习册上传失败：' + errMsg(err, '请稍后重试。')
    console.error(err)
  } finally {
    uploadingWb.value = false
  }
}

async function removeWorkbook() {
  const wb = selectedWorkbook.value
  if (!wb) return
  if (!confirmDeleteWb.value) {
    confirmDeleteWb.value = true
    setTimeout(() => (confirmDeleteWb.value = false), 3000)
    return
  }
  try {
    await teacher.deleteWorkbook(wb.id)
    workbooks.value = workbooks.value.filter((w) => w.id !== wb.id)
    if (Number(workbookId.value) === wb.id) workbookId.value = ''
    confirmDeleteWb.value = false
  } catch (err) {
    error.value = '练习册删除失败：' + errMsg(err, '请稍后重试。')
    console.error(err)
  }
}

// ---------- 按页提题（v0.13.0）：从练习册 PDF 指定页自动识别题目 ----------
// 页码解析+页面渲染在后端是纯程序处理，拆题走视觉模型；返回的草稿题逐道填入
// 题目卡（复用拍照追加的落点逻辑：首行还是空题时先填首行），教师检查后才发布。
const extracting = ref(false)
const extractNote = ref('')

interface ExtractedDraft {
  prompt: string
  knowledge_point: string
  source_page: number
}

async function extractFromPdf() {
  if (!workbookId.value || !pageRange.value.trim() || extracting.value) return
  extracting.value = true
  extractNote.value = ''
  recognitionError.value = ''
  error.value = ''
  try {
    const { data } = await api.post<{
      pages: number[]
      questions: ExtractedDraft[]
      warnings: string[]
    }>(`/api/teacher/workbooks/${workbookId.value}/extract-questions`, {
      page_range: pageRange.value.trim()
    })
    if (!data.questions.length) {
      error.value = data.warnings[0] ?? '这几页没有识别到题目，请检查页码或用拍照补录。'
      return
    }
    for (const draft of data.questions) {
      const first = questions.value[0]
      const firstBlank =
        questions.value.length === 1 && first && !first.prompt.trim() && !first.knowledge_point.trim()
      const q = firstBlank ? first : blankQuestion()
      if (!firstBlank) questions.value.push(q)
      q.prompt = draft.prompt
      if (draft.knowledge_point) q.knowledge_point = draft.knowledge_point
      q.recognized = true
    }
    distributeEvenly() // v0.13.3：识别进来的题先自动均分，教师再按需调整
    extractNote.value =
      `已从第 ${data.pages.join('、')} 页识别出 ${data.questions.length} 道题，填到下方题目卡里了，分值已先自动均分，请逐题检查修改后再发布。` +
      (data.warnings.length ? `（${data.warnings.join(' ')}）` : '')
  } catch (err) {
    recognitionError.value = '自动识别失败：' + recognitionFailureMessage(err, '请稍后重试，或用拍照补录。')
    error.value = recognitionError.value
    console.error(err)
  } finally {
    extracting.value = false
  }
}

// ---------- 拍照识别题目（v0.2.1）：识别结果填入当前题行，教师检查后再发布 ----------
const photoRef = ref<HTMLInputElement | null>(null)
/** 拍照识别的目标题目表单（普通题/小题通用，v0.13.1 改为直接持有表单对象） */
const photoTargetQ = ref<QuestionForm | null>(null)
const photoAppend = ref(false)
const appendRecognizing = ref(false)

function pickPhoto(q: QuestionForm) {
  photoTargetQ.value = q
  photoAppend.value = false
  photoRef.value?.click()
}

/** 线下模式：拍题目页 → 识别 → 追加一道草稿题（第一行还是空题时直接填第一行） */
function pickPhotoAppend() {
  photoTargetQ.value = null
  photoAppend.value = true
  photoRef.value?.click()
}

async function onPhotoChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  recognitionError.value = ''
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    error.value = '题目照片格式不对，请上传 jpg / png / webp 格式的图片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    error.value = '题目照片太大了（超过 10MB），请压缩后再试。'
    return
  }
  const appendMode = photoAppend.value
  let q: QuestionForm
  if (appendMode) {
    appendRecognizing.value = true
    const first = questions.value[0]
    const firstBlank =
      questions.value.length === 1 && first && !first.prompt.trim() && !first.knowledge_point.trim()
    q = firstBlank ? first : blankQuestion()
    if (!firstBlank) questions.value.push(q)
  } else {
    if (!photoTargetQ.value) return
    q = photoTargetQ.value
  }
  const stepsExpandedBeforeRecognition = q.stepsExpanded
  q.recognizing = true
  q.stepsExpanded = false
  error.value = ''
  try {
    const res = await teacher.recognizePhoto(file)
    if (res.question_text) q.prompt = formatRecognizedMath(res.question_text)
    if (res.steps?.length) q.standard_steps_text = formatRecognizedMath(res.steps.join('\n'))
    q.recognized = true
    // v0.13.3：拍照追加的题先自动均分（单题拍照只改本题内容、题数不变，不重排分值）
    if (appendMode) distributeEvenly()
  } catch (err: unknown) {
    q.stepsExpanded = stepsExpandedBeforeRecognition
    recognitionError.value = '照片识别失败：' + recognitionFailureMessage(err, '请稍后重试。')
    error.value = recognitionError.value
    console.error(err)
  } finally {
    q.recognizing = false
    appendRecognizing.value = false
  }
}

// ---------- v0.13.11：拍照识别大题（识别入口在大题层级，不再逐个小题拍） ----------
// 一次识别拆出共同题干 + 全部小题（照片里有解题过程才带每道小题的步骤），
// 填进目标大题（工具栏/空态入口 = 新建一个大题；大题卡头入口 = 替换本大题，
// 已有内容时先确认）。填完与拍照追加同口径：自动均分一次，并逐小题 AI 猜知识点。
const groupPhotoRef = ref<HTMLInputElement | null>(null)
const groupPhotoTarget = ref<GroupForm | null>(null)
const groupRecognizing = ref(false)
const recognitionInProgress = computed(() =>
  groupRecognizing.value || appendRecognizing.value || questions.value.some((question) => question.recognizing)
)

function pickGroupPhoto(g?: GroupForm) {
  if (g) {
    const hasContent = g.stem.trim() || g.subs.some((s) => s.prompt.trim() || s.standard_steps_text.trim())
    if (hasContent && !window.confirm('将用识别结果替换这个大题的题干与全部小题，继续？')) return
    groupPhotoTarget.value = g
  } else {
    groupPhotoTarget.value = null
  }
  groupPhotoRef.value?.click()
}

async function onGroupPhotoChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  recognitionError.value = ''
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    error.value = '大题照片格式不对，请上传 jpg / png / webp 格式的图片。'
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    error.value = '大题照片太大了（超过 10MB），请压缩后再试。'
    return
  }
  const target = groupPhotoTarget.value
  const previousStepsExpanded = new Map(target?.subs.map((sub) => [sub, sub.stepsExpanded]) ?? [])
  target?.subs.forEach((sub) => { sub.stepsExpanded = false })
  groupRecognizing.value = true
  error.value = ''
  try {
    const res = await teacher.recognizeGroupPhoto(file)
    const subs = (res.sub_questions ?? []).map((s) => {
      const sf = blankQuestion()
      sf.prompt = formatRecognizedMath(s.question_text ?? '')
      sf.standard_steps_text = formatRecognizedMath((s.steps ?? []).join('\n'))
      sf.stepsExpanded = false
      sf.recognized = true
      return sf
    })
    let g = groupPhotoTarget.value
    if (!g) {
      g = { ...blankGroup(), subs: [] }
      groups.value.push(g)
    }
    g.stem = formatRecognizedMath(res.stem ?? '')
    g.diagram = null
    g.diagramMessage = ''
    g.subs = subs.length ? subs : [blankQuestion()]
    distributeEvenly()
    const gi = groups.value.indexOf(g)
    g.subs.forEach((sf, si) => {
      if (sf.prompt.trim() && !sf.knowledge_point) void guessKp(sf, `大题 ${gi + 1} 小题（${si + 1}）`)
    })
  } catch (err: unknown) {
    previousStepsExpanded.forEach((expanded, sub) => { sub.stepsExpanded = expanded })
    recognitionError.value = '大题识别失败：' + recognitionFailureMessage(err, '请换一张更清晰的照片重试。')
    error.value = recognitionError.value
    console.error(err)
  } finally {
    groupRecognizing.value = false
    groupPhotoTarget.value = null
  }
}

async function submit() {
  error.value = ''
  showRequiredHints.value = true
  if (!title.value.trim()) {
    titleInputRef.value?.focus()
    titleInputRef.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  if (!selectedClassIds.value.length) {
    const target = classSectionRef.value?.querySelector<HTMLElement>('.recipient-class input[type="checkbox"]')
      ?? classSectionRef.value?.querySelector<HTMLElement>('a')
      ?? classSectionRef.value
    target?.focus()
    target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  // 截止时间不能早于当前时间（日历已置灰过去的日期，时刻仍可能选到已过点，这里兜底再拦一次）
  if (deadline.value && new Date(deadline.value).getTime() <= Date.now()) {
    error.value = '截止时间不能早于当前时间，请重新选择截止时间。'
    return
  }
  if (mode.value === 'offline') {
    if (!workbookId.value) {
      wbOpen.value = true // 折叠着的时候报错也要把卡片展开，方便直接补选
      error.value = '线下作业要先选一本练习册（知识库是空的就先上传整本 PDF）。'
      return
    }
    if (!pageRange.value.trim()) {
      wbOpen.value = true
      error.value = '请填写页码 / 题号范围，学生才知道做练习册的哪一部分。'
      return
    }
  }
  // 没加题目不能发；题干必须完整，知识点允许留空，避免等待 AI 知识点识别。
  // 待发布清单与页面渲染顺序一致（小题在前、
  // 大题小题随后），后端按数组顺序落 order_num；label 供报错定位。
  if (!questions.value.length && !groups.value.length) {
    error.value = '还没有添加题目，请先点「添加小题」或「添加大题」。'
    return
  }
  interface Entry { q: QuestionForm; label: string; groupKey: string | null }
  const entries: Entry[] = []
  for (let i = 0; i < questions.value.length; i++) {
    const q = questions.value[i]
    if (!q.prompt.trim()) {
      error.value = `第 ${i + 1} 题还没填写题干，填完或删除这一题后再发布。`
      return
    }
    entries.push({ q, label: `第 ${i + 1} 题`, groupKey: null })
  }
  const groupPayload: { key: string; stem: string; diagram?: FigureSpec | null; diagram_job_id?: number }[] = []
  for (let gi = 0; gi < groups.value.length; gi++) {
    const g = groups.value[gi]
    if (!g.stem.trim()) {
      error.value = `大题 ${gi + 1} 的题干还没填写（小题要靠它给材料）。`
      return
    }
    if (!g.subs.length) {
      error.value = `大题 ${gi + 1} 还没有小题，请添加小题或删除这个大题。`
      return
    }
    const key = `g${gi + 1}`
    groupPayload.push({ key, stem: g.stem.trim(), diagram: g.diagram || undefined, diagram_job_id: g.diagramJobId && g.diagramPrompt === groupFigurePrompt(g) && g.diagramSubject === subject.value ? g.diagramJobId : undefined })
    for (let si = 0; si < g.subs.length; si++) {
      const sub = g.subs[si]
      if (!sub.prompt.trim()) {
        error.value = `大题 ${gi + 1} 的小题（${si + 1}）还没填写题干，填完或删除后再发布。`
        return
      }
      entries.push({ q: sub, label: `大题 ${gi + 1} 小题（${si + 1}）`, groupKey: key })
    }
  }
  const valid = entries.map((e) => e.q)
  // 评分系统：总分合法性 + 分值占比合计必须 = 100%（容差 0.5），否则拦截发布
  const total = Number(totalScore.value)
  if (!total || Number.isNaN(total) || total <= 0) {
    error.value = '请填写有效的作业总分（满分）。'
    return
  }
  if (!weightSumOk.value) {
    error.value = weightSum.value < 100
      ? `分值占比合计是 ${fmtScore(weightSum.value)}%，还差 ${fmtScore(100 - weightSum.value)}%，请调整各题占比或点「一键均分」后再发布。`
      : `分值占比合计是 ${fmtScore(weightSum.value)}%，超出了 ${fmtScore(weightSum.value - 100)}%，请调整各题占比或点「一键均分」后再发布。`
    return
  }
  // 发布前批量验算参考答案（v0.9.3）：填了答案的题全部验一遍；
  // suspect 只在题下留黄色标记并弹一次确认，教师确认后照常发布，绝不拦截
  const withAnswer = subject.value === 'math' ? valid.filter((q) => q.reference_answer.trim()) : []
  if (withAnswer.length) {
    // 知识点识别是独立的异步辅助任务，识别结果到达不能让发布校验失效。
    const checkedStamps = new Map(withAnswer.map((q) => [q, answerCheckStampOf(q)]))
    checkingAll.value = true
    try {
      await Promise.all(withAnswer.map((q) => runCheck(q)))
    } catch (e) {
      console.error(e) // runCheck 内部已兜底，这里只防万一：验算出问题不挡发布
    } finally {
      checkingAll.value = false
    }
    if (withAnswer.some((q) => answerCheckStampOf(q) !== checkedStamps.get(q))) {
      error.value = '验算期间题干或参考答案有改动，请再次点击发布以检查最新内容。'
      return
    }
    const suspects = withAnswer.filter((q) => showResult(q) && q.check_status === 'suspect')
    if (suspects.length) {
      const labelByQuestion = new Map<(typeof entries)[number]['q'], string>()
      for (const entry of entries) {
        if (!labelByQuestion.has(entry.q)) labelByQuestion.set(entry.q, entry.label)
      }
      const nums = suspects.map((q) => labelByQuestion.get(q) ?? '某题').join('、')
      const go = window.confirm(
        `有 ${suspects.length} 道题的参考答案可能有误（${nums}），验算说明已标在对应题目下方。\n` +
        'AI 验算只是提醒，确认仍要发布吗？'
      )
      if (!go) return
    }
  }
  const payload: TeacherAssignmentInput = {
    title: title.value.trim(),
    subject: subject.value,
    class_ids: [...selectedClassIds.value],
    total_score: total,
    // v0.13.1：允许修改开关 + 大题（小题经 group_key 挂靠 groups）
    allow_revision: allowRevision.value,
    groups: groupPayload,
    questions: entries.map((e) => ({
      // type 保留旧接口兼容；subject 保存这道题的实际学科。
      type: subject.value === 'math' ? 'math' as const : 'essay' as const,
      subject: subject.value,
      prompt: e.q.prompt.trim(),
      knowledge_point: e.q.knowledge_point.trim(),
      standard_steps: e.q.standard_steps_text.split('\n').map((s) => s.trim()).filter(Boolean),
      reference_answer: e.q.reference_answer.trim() || undefined,
      // 评分系统：填了占比才下发；留空的题后端按题数均分
      weight_pct: e.q.weight_pct === null || e.q.weight_pct === undefined || Number.isNaN(Number(e.q.weight_pct))
        ? undefined
        : Number(e.q.weight_pct),
      group_key: e.groupKey ?? undefined
    }))
  }
  // 空数组的 standard_steps 不下发，保持请求干净
  payload.questions.forEach((q) => {
    if (!q.standard_steps?.length) delete q.standard_steps
  })
  // 说明与截止时间（v0.13.1）：两种模式都下发，此前截止只在线下分支里、说明根本没进 payload
  if (description.value.trim()) payload.description = description.value.trim()
  if (deadline.value) payload.deadline = deadline.value.length === 16 ? `${deadline.value}:00` : deadline.value
  if (mode.value === 'offline') {
    payload.mode = 'offline'
    payload.workbook_id = Number(workbookId.value)
    payload.page_range = pageRange.value.trim()
  }
  submitting.value = true
  try {
    const assignment = await teacher.createAssignment(payload)
    ok.value = true
    if (props.embedded) emit('published', assignment)
    else {
      teacher.setAssignmentDateFilter('')
      window.dispatchEvent(new CustomEvent('assignments-changed'))
      setTimeout(() => router.push('/teacher/assignments/manage'), 600)
    }
  } catch (e: unknown) {
    error.value = '发布失败：' + errMsg(e, '请稍后重试。')
    console.error(e)
  } finally {
    submitting.value = false
  }
}

onBeforeRouteLeave(() => {
  if (props.embedded || ok.value) return
  const hasQuestionContent = (q: QuestionForm) => !!(q.prompt.trim() || q.knowledge_point.trim() || q.standard_steps_text.trim() || q.reference_answer.trim())
  const hasDraft = !!(title.value.trim() || description.value.trim() || pageRange.value.trim() || deadline.value || workbookId.value || allowRevision.value || totalScore.value !== 100 || selectedClassIds.value.length || questions.value.some(hasQuestionContent) || groups.value.some((group) => group.stem.trim() || group.subs.some(hasQuestionContent)))
  if (hasDraft && !window.confirm('作业内容尚未发布，确定离开吗？')) return false
})

onMounted(async () => {
  await Promise.all([
    loadWorkbooks(),
    teacher.fetchClassrooms().then((items) => { classrooms.value = items }),
  ])
  // 带 mode 的链接直达第二级表单（v0.12.0）：书架跳入 ?mode=offline&workbook_id=<id>、
  // 第一级选方式时写入的 ?mode= 刷新后都停在表单级
  if (!props.chatWorkflow && (route.query.mode === 'offline' || route.query.mode === 'online')) {
    mode.value = route.query.mode
    step.value = 'form'
    const wid = Number(route.query.workbook_id)
    if (wid && workbooks.value.some((w) => w.id === wid)) {
      workbookId.value = wid
      wbOpen.value = true // 深链已带选好的书，直接展开范围卡方便接着填页码
    }
  }
})
</script>

<style scoped>
.figure-progress { margin: 10px 0; max-width: 360px; color: var(--text-2); font-size: 13px; }
.figure-progress :deep(.progress-track) { margin-top: 5px; }
/* ---------- 两级导航（v0.12.0） ---------- */
/* v0.13.1 修复「选模式后错位」：此前选择级是 880px 居中窄列、表单级是整幅宽，
   点卡进入表单时内容突然变宽并整体左移，看起来像错位。两级统一为同一内容列宽。 */
.chat-workflow-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 14px; color: var(--text); font-size: 14px; font-weight: 650; }
.chat-workflow-head > span { display: inline-flex; align-items: center; gap: 8px; }
.publish-page.is-chat-workflow { padding-top: 14px; }
.publish-page.is-chat-workflow.is-chat-workflow-collapsed { padding-top: 0; padding-bottom: 0; }
.publish-page.is-chat-workflow-collapsed .chat-workflow-head { margin-bottom: 0; }
/* v0.13.11：红色警示悬浮 toast（固定在视口顶部居中，盖在内容之上，不占位） */
.error-toast {
  position: fixed; top: 18px; left: 50%; transform: translateX(-50%);
  z-index: 200; display: flex; align-items: center; gap: 8px;
  max-width: min(92vw, 560px); padding: 11px 16px; border-radius: var(--radius-control);
  background: var(--red-bg); color: var(--red-strong); border: 1px solid var(--red-border);
  box-shadow: var(--shadow-md); font-size: 14px; font-weight: 600; line-height: 1.5;
}
.error-toast svg { flex-shrink: 0; }
.toast-fade-enter-active, .toast-fade-leave-active { transition: opacity .25s ease, transform .25s ease; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; transform: translate(-50%, -8px); }
.ph-main { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.ph-main h2 { margin: 0; }
.page-head.publish-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.publish-page.is-embedded { max-width: none; width: 100%; margin: 0; padding: 18px 0 0; }
.publish-page.is-embedded .page-head { margin-bottom: 14px; }
.subject-field-label { display: block; margin-bottom: 7px; color: var(--text-strong); font-size: 13px; font-weight: 620; }
.publish-page .card.picker-open { position: relative; z-index: 20; }
.subject-picker, .recipient-picker { position: relative; width: 100%; }
.recipient-picker { width: min(100%, 440px); margin-top: 12px; }
.subject-select, .recipient-select {
  width: 100%; min-height: 52px; display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 14px; border: 1.5px solid var(--border-strong); border-radius: var(--radius-control);
  background: #FBFCFF; color: var(--text); font: inherit; text-align: left; cursor: pointer;
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
}
.subject-select { font-size: 16px; font-weight: 650; }
.recipient-select { min-height: 56px; }
.subject-select:hover, .recipient-select:hover,
.subject-select[aria-expanded='true'], .recipient-select[aria-expanded='true'] { border-color: var(--primary); background: #fff; }
.subject-select:focus-visible, .recipient-select:focus-visible {
  outline: none; border-color: var(--primary); background: #fff; box-shadow: 0 0 0 3px var(--primary-50);
}
.recipient-select[aria-invalid='true'] { border-color: var(--red); }
.picker-chevron { flex: 0 0 auto; color: var(--text-2); transition: transform .16s ease, color .16s ease; }
.picker-chevron.open { color: var(--primary); transform: rotate(180deg); }
.subject-menu, .recipient-menu {
  position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 80;
  padding: 6px; overflow-y: auto; background: var(--card); border: 1px solid var(--border);
  border-radius: var(--radius-control); box-shadow: var(--shadow-md);
  animation: publish-pane-in .16s ease both;
}
.subject-menu { max-height: min(280px, 48vh); }
.recipient-menu { max-height: min(340px, 52vh); }
.subject-option, .recipient-option {
  width: 100%; min-height: 44px; display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border: 0; border-radius: var(--radius-detail); background: transparent;
  color: var(--text); text-align: left; cursor: pointer; transition: background .12s ease, color .12s ease;
}
.subject-option:hover, .recipient-option:hover { background: var(--primary-50); }
.subject-option.is-selected, .recipient-option.is-selected { background: var(--primary-50); color: var(--primary); }
.subject-option input, .recipient-option input { width: 18px; height: 18px; flex: 0 0 auto; margin: 0; accent-color: var(--primary); }
.subject-option span { font-weight: 600; }
.recipient-option { min-height: 52px; }
.recipient-option-info { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.recipient-option-info b { font-size: 14px; font-weight: 600; }
.recipient-option-info small, .recipient-selection small { color: var(--text-3); font-size: 12px; }
.recipient-option-check { flex: 0 0 auto; color: var(--primary); }
.recipient-selection { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
.recipient-selection-name { max-width: 100%; overflow: hidden; color: var(--text-strong); font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.recipient-placeholder { color: var(--text-3); font-size: 14px; }
.class-empty { padding-top: 10px; color: var(--text-3); font-size: 12px; }
/* ---------- 表单布局：按实际位置并排，不再逐行堆叠 ---------- */
.grid-3 { display: grid; grid-template-columns: 1fr 1.1fr 1.3fr; gap: 14px; margin-bottom: 14px; }
.grid-q-meta { display: grid; grid-template-columns: 1.5fr 1fr 1.3fr; gap: 14px; margin-bottom: 14px; }
.grid-3 .form-row, .grid-q-meta .form-row { margin-bottom: 0; }
@media (max-width: 760px) {
  .grid-3, .grid-q-meta { grid-template-columns: 1fr; }
}
/* ---------- v0.13.4：练习册折叠卡 / 时间限制面板（自制日历） ---------- */
.opt-dot { background: var(--primary); color: #fff; font-size: 11px; font-weight: 700; border-radius: var(--radius-pill); padding: 1px 7px; }
.fold-head {
  width: 100%; display: flex; align-items: center; gap: 12px;
  background: none; border: none; padding: 0; cursor: pointer;
  font-family: var(--font); color: var(--text); text-align: left;
}
.fold-sum { flex: 1; font-size: 13px; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fold-body { margin-top: 14px; animation: publish-pane-in .25s ease both; }
.time-field {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 10px 12px; cursor: pointer; font-family: var(--font); font-size: 14px; color: var(--text);
  background: #FBFCFF; border: 1.5px solid var(--border-strong); border-radius: var(--radius-control);
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
}
.time-field:hover, .time-field:focus-visible { border-color: var(--primary); background: #fff; box-shadow: 0 0 0 3px var(--primary-50); outline: none; }
.time-field-text { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.time-panel {
  border: 1.5px solid var(--border-strong); border-radius: var(--radius-surface); background: #FBFCFF;
  padding: 14px; margin-bottom: 14px; animation: publish-pane-in .25s ease both;
}
.time-grid { display: grid; grid-template-columns: 288px 1fr; gap: 20px; }
@media (max-width: 900px) { .time-grid { grid-template-columns: 1fr; } }
.cal-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.cal-title { font-weight: 700; font-size: 14.5px; }
.cal-nav {
  width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center;
  border: 1.5px solid var(--border); border-radius: var(--radius-detail); background: #fff; color: var(--text); cursor: pointer;
}
.cal-nav:hover { border-color: var(--primary); color: var(--primary); }
.cal-week, .cal-days { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.cal-week span { text-align: center; font-size: 11.5px; color: var(--text-3); padding: 2px 0; }
.cal-day {
  height: 34px; border: 1px solid transparent; border-radius: var(--radius-detail); background: transparent;
  cursor: pointer; font-family: var(--font); font-size: 13px; color: var(--text);
  transition: border-color .12s ease, background .12s ease, color .12s ease;
}
.cal-day:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.cal-day.today { border-color: #B7C9F5; font-weight: 700; }
.cal-day.sel { background: var(--primary); color: #fff; font-weight: 700; }
.cal-day:disabled { color: var(--text-3); opacity: .4; cursor: not-allowed; }
.cal-day.blank { visibility: hidden; }
.time-pick-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.time-pick-row select { width: auto; padding: 8px 10px; }
.time-colon { font-weight: 700; }
.quick-row { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.quick-chip {
  border: 1.5px solid var(--border); background: #fff; color: var(--text-2);
  border-radius: var(--radius-pill); padding: 4px 11px; font-size: 12.5px; cursor: pointer; font-family: var(--font);
  transition: border-color .12s ease, color .12s ease, background .12s ease;
}
.quick-chip:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-50); }
.deadline-warn { margin-top: 8px; font-size: 12.5px; color: var(--amber-strong); }
.desc-row { margin-bottom: 14px; }
.desc-area textarea { overflow-y: auto; resize: none; transition: height .18s ease; }
.check-notes { margin: -6px 0 12px; }
.check-notes .check-note { margin-top: 0; }
/* ---------- 输入控件统一样式（全局裸样式太素，含 number/datetime 的补齐） ---------- */
.publish-page input[type='text'], .publish-page input[type='number'],
.publish-page input[type='datetime-local'], .publish-page textarea, .publish-page select {
  border: 1.5px solid var(--border-strong); border-radius: var(--radius-control); background: #FBFCFF;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.publish-page input[type='number'], .publish-page input[type='datetime-local'] {
  width: 100%; padding: 10px 12px; font-size: 14px; font-family: inherit; color: var(--text);
}
.publish-page input:focus, .publish-page textarea:focus, .publish-page select:focus {
  background: #fff; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-50); outline: none;
}
.publish-page select:disabled { background: #F1F4F9; color: var(--text-3); cursor: not-allowed; }
.publish-page .score-input { width: 110px; }
.required-mark { margin-left: 6px; color: var(--red); font-size: 12px; font-weight: 600; }
.field-required-error { margin-top: 6px; color: var(--red); font-size: 12px; line-height: 1.4; }
/* ---------- 底部吸底操作条 ---------- */
.publish-actions {
  position: sticky; bottom: 14px; z-index: 5;
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-surface);
  box-shadow: var(--shadow-md); padding: 12px 14px; margin-bottom: 16px;
}
.publish-actions .spacer { flex: 1; }
.recognition-error { display: inline-flex; align-items: center; gap: 5px; max-width: 440px; color: var(--red); font-size: 12px; line-height: 1.4; }
.recognition-progress-status { display: flex; flex: 1 0 100%; align-items: center; gap: 12px; color: var(--text-2); font-size: 12px; }
.recognition-progress-track { width: min(280px, 42vw); height: 5px; overflow: hidden; border-radius: var(--radius-pill); background: var(--primary-50); }
.recognition-progress-indicator { display: block; width: 34%; height: 100%; border-radius: inherit; background: var(--primary); animation: recognition-progress-slide 1.35s ease-in-out infinite; }
@keyframes recognition-progress-slide {
  from { transform: translateX(-110%); }
  to { transform: translateX(310%); }
}
.weight-mini { font-size: 13px; color: var(--text-2); }
.weight-mini b { color: var(--green); }
.weight-mini.bad b { color: var(--red); }
.q-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; gap: 10px; flex-wrap: wrap; }
.q-actions { display: flex; gap: 8px; align-items: center; }
/* ---------- v0.13.3：选书按钮与页码同行 / 书架选书面板 ---------- */
.wb-pick-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
.wb-pick-row .form-row { margin-bottom: 0; }
@media (max-width: 760px) { .wb-pick-row { grid-template-columns: 1fr; } }
.wb-pick-btn {
  width: 100%; display: flex; align-items: center; gap: 9px;
  padding: 10px 12px; cursor: pointer; font-family: var(--font); font-size: 14px; color: var(--text);
  background: #FBFCFF; border: 1.5px solid var(--border-strong); border-radius: var(--radius-control);
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
}
.wb-pick-btn:hover, .wb-pick-btn:focus-visible { border-color: var(--primary); background: #fff; box-shadow: 0 0 0 3px var(--primary-50); outline: none; }
.wb-pick-name { flex: 1; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.shelf-mask {
  position: fixed; inset: 0; z-index: 60;
  background: rgba(15, 23, 42, .45);
  display: flex; align-items: center; justify-content: center; padding: 18px;
  animation: publish-pane-in .25s ease both;
}
.shelf-panel {
  width: min(680px, 100%); max-height: 82vh; overflow-y: auto;
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-panel); padding: 18px;
  box-shadow: var(--shadow-lg);
}
.shelf-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.shelf-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.shelf-thumb { width: 108px; padding: 8px 8px 7px; }
.shelf-thumb img { width: 62px; height: 83px; }
.shelf-thumb .wb-thumb-spine { width: 62px; height: 83px; }
.shelf-thumb .wb-thumb-name { max-width: 92px; font-size: 12px; }
.shelf-actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 16px; border-top: 1px dashed var(--border); padding-top: 14px; }
.shelf-actions a.btn { text-decoration: none; }
/* 练习册封面缩略图（v0.6.0，现仅用于书架面板） */
.wb-thumb {
  width: 76px; padding: 6px 6px 5px; cursor: pointer; font-family: var(--font); color: var(--text);
  background: #fff; border: 1px solid var(--border-strong); border-radius: var(--radius-control);
  display: flex; flex-direction: column; align-items: center; gap: 5px;
  transition: border-color 0.2s ease, transform 0.2s ease;
}
.wb-thumb:hover { transform: translateY(-1px); }
.wb-thumb.active { border-color: var(--primary); background: var(--primary-50); }
.wb-thumb img { width: 44px; height: 59px; object-fit: cover; border-radius: var(--radius-book); box-shadow: 0 3px 7px rgba(15, 23, 42, 0.2); }
.wb-thumb-spine {
  width: 44px; height: 59px; border-radius: var(--radius-book);
  background: var(--primary-50); color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.wb-thumb-name {
  font-size: 11px; line-height: 1.3; max-width: 64px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.kp-row { display: flex; gap: 8px; align-items: center; }
.kp-row input { flex: 1; }
.kp-row .btn { flex: none; }
.extract-row { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; margin-top: 14px; }
.extract-row .hint { flex: 1; min-width: 240px; line-height: 1.55; }
.btn.danger-outline { background: #fff; color: var(--red); border: 1px solid var(--red-border); }
.btn.danger-outline:hover { background: var(--red-bg); }
/* 评分系统：总分/占比输入与合计条 */
.score-input-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.score-input { width: 110px; flex: none; }
.weight-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 13px 18px; }
.weight-sum { font-size: 14px; }
.weight-sum b { color: var(--green); font-size: 16px; }
.weight-sum.bad b { color: var(--red); }
.weight-bar .hint { flex: 1; min-width: 200px; }
.weight-bar .btn { margin-left: auto; }
.offline-photo-card { border: 1px dashed #B7C9F5; background: #FBFCFF; }
/* 参考答案 AI 验算（v0.9.3） */
.card.q-suspect { border: 1.5px solid var(--amber); background: var(--amber-bg); }
/* ---------- v0.13.1：允许修改勾选 / 大题 / 标准步骤符号栏 / 过渡动画 ---------- */
.revision-check {
  display: flex; align-items: center; gap: 8px;
  min-height: 38px; font-size: 13.5px; font-weight: 600; color: var(--text);
  cursor: pointer;
}
.publish-page .revision-check input[type="checkbox"] {
  width: 17px; height: 17px; flex: none; margin: 0;
  accent-color: var(--primary); cursor: pointer;
}
.figure-message { margin-top: 8px; }
.group-material.has-figure { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: start; }
.figure-preview { display: flex; min-width: 0; flex-direction: column; align-items: center; }
@media (max-width: 760px) { .group-material.has-figure { grid-template-columns: minmax(0, 1fr); gap: 0; } }
.sub-block {
  border-top: 1px dashed var(--border);
  padding-top: 14px; margin-top: 14px;
}
.sub-block:first-of-type { border-top: none; padding-top: 4px; }
.steps-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.steps-heading label { min-width: 0; }
.steps-chevron-up { transform: rotate(180deg); }
.steps-toggle { margin-bottom: 14px; }
.symbol-bar { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.symbol-btn {
  min-width: 38px; height: 34px; padding: 0 9px;
  border: 1.5px solid var(--border); border-radius: var(--radius-detail);
  background: var(--bg); color: var(--text);
  font-size: 15px; font-weight: 600; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  transition: border-color .15s ease, color .15s ease, background .15s ease, transform .1s ease;
}
.symbol-btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-50); }
.symbol-btn:active { transform: translateY(1px); }
/* 两级切换与卡片入场：淡入 + 轻微上移，选方式 → 进表单不再是硬切 */
@keyframes publish-pane-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.publish-page .card {
  animation: publish-pane-in .32s ease both;
}
.publish-actions { animation: publish-pane-in .32s ease both; }
.check-note { display: flex; align-items: flex-start; gap: 5px; font-size: 12.5px; line-height: 1.5; margin-top: 7px; }
.check-note .check-ic { flex: none; display: inline-flex; margin-top: 1px; }
.check-note.ok { color: var(--green); align-items: center; }
.check-note.ok .check-ic { margin-top: 0; }
.check-note.warn { color: var(--amber-strong); }
.check-note.muted { color: var(--text-3); }
@media (prefers-reduced-motion: reduce) {
  .recognition-progress-indicator { width: 100%; animation: none; }
}
</style>
