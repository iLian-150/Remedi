<!-- 全局布局
     学生端：顶部导航（作业列表 / 诊断报告 / 订正错题 / 我的档案）+ 卡片式页面
     教师端：左侧导航（总览 / 批改 / 学生 / 教学建议）+ 顶栏班级切换器（MVP 占位下拉） -->
<template>
  <!-- 教师端布局 -->
  <div v-if="auth.role === 'teacher' && auth.token" class="teacher-shell">
    <aside class="sidebar">
      <div class="sidebar-brand">Remedi<small>教师端 · 班级诊断</small></div>
      <nav class="sidebar-nav">
        <router-link to="/teacher/dashboard" active-class="active">📊 总览</router-link>
        <router-link to="/teacher/submissions" active-class="active">📝 批改</router-link>
        <router-link to="/teacher/students" active-class="active">👥 学生</router-link>
        <router-link to="/teacher/suggestions" active-class="active">💡 教学建议</router-link>
      </nav>
      <div class="sidebar-foot">Remedi MVP · 数据仅用于演示</div>
    </aside>
    <div class="teacher-main">
      <header class="topbar">
        <!-- MVP 占位：当前仅支持单个演示班级 -->
        <select class="class-switcher" disabled title="MVP 占位：当前仅支持单个演示班级，二期开放多班级切换">
          <option>演示班级</option>
        </select>
        <div class="user-info">
          <span>{{ auth.name }}（教师）</span>
          <button class="btn small secondary" @click="logout">退出</button>
        </div>
      </header>
      <router-view />
    </div>
  </div>

  <!-- 学生端 / 未登录布局 -->
  <div v-else>
    <nav class="topbar">
      <span class="brand">Remedi<small>智能作业诊断</small></span>
      <div class="nav" v-if="auth.role === 'student'">
        <router-link to="/student/assignments" active-class="active">作业列表</router-link>
        <router-link to="/student/feedback" active-class="active">诊断报告</router-link>
        <router-link to="/student/corrections" active-class="active">订正错题</router-link>
        <router-link to="/student/profile" active-class="active">我的档案</router-link>
      </div>
      <div class="user-info" v-if="auth.token">
        <span>{{ auth.name }}（学生）</span>
        <button class="btn small secondary" @click="logout">退出</button>
      </div>
    </nav>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { useAuthStore } from './stores/auth'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/')
}
</script>
