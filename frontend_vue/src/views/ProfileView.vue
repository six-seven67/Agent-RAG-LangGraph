<template>
  <div class="profile-page">
    <h1>👤 个人中心</h1>
    <p class="page-desc">管理您的账户信息与安全设置</p>

    <!-- 基本信息 -->
    <div class="card">
      <h3>基本信息</h3>
      <div v-if="profile">
        <div class="info-row"><span class="info-label">用户 ID</span><span class="info-value">{{ profile.id }}</span></div>
        <div class="info-row"><span class="info-label">用户名</span><span class="info-value">{{ profile.username }}</span></div>
        <div class="info-row"><span class="info-label">邮箱</span><span class="info-value">{{ profile.email || '未设置' }}</span></div>
        <div class="info-row"><span class="info-label">状态</span><span class="info-value">{{ profile.is_active ? '✅ 正常' : '🚫 已禁用' }}</span></div>
        <div class="info-row"><span class="info-label">注册时间</span><span class="info-value">{{ profile.created_at || '-' }}</span></div>
      </div>
      <div v-else-if="profileLoading" style="padding:1rem 0">
        <div v-for="n in 4" :key="'sk-'+n" style="display:flex;align-items:center;gap:0.75rem;padding:0.5rem 0">
          <div class="skeleton" style="width:80px;height:14px;flex-shrink:0"></div>
          <div class="skeleton" style="width:200px;height:14px"></div>
        </div>
      </div>
      <div v-else class="text-secondary">暂无数据</div>
    </div>

    <!-- 修改邮箱 -->
    <div class="card">
      <h3>修改邮箱</h3>
      <form @submit.prevent="handleUpdateEmail">
        <div style="display:flex;gap:0.75rem;align-items:flex-end;flex-wrap:wrap">
          <div class="form-group flex-1" style="margin-bottom:0;min-width:200px">
            <label class="form-label" for="profile-email">新邮箱地址</label>
            <input class="form-input" id="profile-email" v-model="email" type="email"
                   placeholder="newemail@example.com">
          </div>
          <button type="submit" class="btn btn-primary" :disabled="emailLoading">
            {{ emailLoading ? '保存中...' : '保存' }}
          </button>
        </div>
        <Transition name="fade">
          <div v-if="emailMsg" class="mt-sm" :style="{ color: emailMsgColor }">{{ emailMsg }}</div>
        </Transition>
      </form>
    </div>

    <!-- 修改密码 -->
    <div class="card">
      <h3>修改密码</h3>
      <form @submit.prevent="handleChangePassword">
        <div class="form-group">
          <label class="form-label" for="old-password">当前密码</label>
          <input class="form-input" id="old-password" v-model="oldPassword" type="password"
                 placeholder="请输入当前密码" autocomplete="current-password" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="new-password">新密码</label>
          <input class="form-input" id="new-password" v-model="newPassword" type="password"
                 placeholder="6-128字符" autocomplete="new-password" required minlength="6">
        </div>
        <div class="form-group">
          <label class="form-label" for="confirm-password">确认新密码</label>
          <input class="form-input" id="confirm-password" v-model="confirmPassword" type="password"
                 placeholder="请再次输入新密码" autocomplete="new-password" required>
        </div>
        <Transition name="fade">
          <div v-if="pwdMsg" class="mt-sm" :style="{ color: pwdMsgColor }">{{ pwdMsg }}</div>
        </Transition>
        <button type="submit" class="btn btn-primary" :disabled="pwdLoading">
          {{ pwdLoading ? '修改中...' : '修改密码' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useToastStore } from '../stores/toast.js'
import * as API from '../api/index.js'

const toast = useToastStore()

const profile = ref(null)
const profileLoading = ref(true)
const email = ref('')
const emailLoading = ref(false)
const emailMsg = ref('')
const emailMsgColor = ref('')

const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const pwdLoading = ref(false)
const pwdMsg = ref('')
const pwdMsgColor = ref('')

onMounted(() => { loadProfile() })

async function loadProfile() {
  profileLoading.value = true
  try {
    const data = await API.getProfile()
    profile.value = data
    if (data.email) email.value = data.email
  } catch (err) {
    toast.error(err.message)
  } finally {
    profileLoading.value = false
  }
}

async function handleUpdateEmail() {
  emailLoading.value = true; emailMsg.value = ''
  try {
    await API.updateProfile(email.value.trim() || undefined)
    emailMsg.value = email.value.trim() ? '邮箱更新成功' : '邮箱已清除'
    emailMsgColor.value = 'var(--color-success)'
    loadProfile()
  } catch (err) {
    emailMsg.value = err.message
    emailMsgColor.value = 'var(--color-danger)'
  } finally {
    emailLoading.value = false
  }
}

async function handleChangePassword() {
  if (newPassword.value !== confirmPassword.value) {
    pwdMsg.value = '两次新密码输入不一致'
    pwdMsgColor.value = 'var(--color-danger)'
    return
  }
  if (newPassword.value.length < 6) {
    pwdMsg.value = '新密码至少需要6个字符'
    pwdMsgColor.value = 'var(--color-danger)'
    return
  }
  pwdLoading.value = true; pwdMsg.value = ''
  try {
    const result = await API.changePassword(oldPassword.value, newPassword.value)
    pwdMsg.value = result.message || '密码修改成功'
    pwdMsgColor.value = 'var(--color-success)'
    oldPassword.value = ''; newPassword.value = ''; confirmPassword.value = ''
    toast.success('密码修改成功')
  } catch (err) {
    pwdMsg.value = err.message
    pwdMsgColor.value = 'var(--color-danger)'
  } finally {
    pwdLoading.value = false
  }
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .2s ease, transform .2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
