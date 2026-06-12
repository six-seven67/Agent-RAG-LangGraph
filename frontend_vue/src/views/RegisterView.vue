<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>📝 注册新账号</h1>
      <p class="subtitle">加入 Agent 智能客服系统</p>
      <form @submit.prevent="handleRegister">
        <div class="form-group">
          <label class="form-label" for="reg-username">用户名 <span class="required">*</span></label>
          <input class="form-input" id="reg-username" v-model="username" type="text"
                 placeholder="2-50字符，支持字母/数字/下划线/中文" autocomplete="username" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg-email">邮箱 <span class="text-secondary">(选填)</span></label>
          <input class="form-input" id="reg-email" v-model="email" type="email"
                 placeholder="example@mail.com" autocomplete="email">
        </div>
        <div class="form-group">
          <label class="form-label" for="reg-password">密码 <span class="required">*</span></label>
          <input class="form-input" id="reg-password" v-model="password" type="password"
                 placeholder="6-128字符" autocomplete="new-password" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg-password2">确认密码 <span class="required">*</span></label>
          <input class="form-input" id="reg-password2" v-model="password2" type="password"
                 placeholder="请再次输入密码" autocomplete="new-password" required>
        </div>
        <Transition name="fade">
          <div v-if="errorMsg" class="form-error">{{ errorMsg }}</div>
        </Transition>
        <button type="submit" class="btn btn-primary btn-lg" style="width:100%;margin-top:0.5rem"
                :disabled="loading">
          <span v-if="loading" class="typing-indicator" style="display:inline-flex">
            <span></span><span></span><span></span>
          </span>
          <span v-else>注 册</span>
        </button>
      </form>
      <div class="auth-footer">
        已有账号？<router-link to="/login">立即登录 →</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { register } from '../api/index.js'

const router = useRouter()
const username = ref('')
const email = ref('')
const password = ref('')
const password2 = ref('')
const errorMsg = ref('')
const loading = ref(false)

async function handleRegister() {
  if (!username.value.trim() || !password.value) {
    errorMsg.value = '用户名和密码为必填项'
    return
  }
  if (password.value !== password2.value) {
    errorMsg.value = '两次密码输入不一致'
    return
  }
  if (password.value.length < 6) {
    errorMsg.value = '密码至少需要6个字符'
    return
  }
  errorMsg.value = ''
  loading.value = true
  try {
    await register(username.value.trim(), password.value, email.value.trim() || undefined)
    router.push('/chat')
  } catch (err) {
    errorMsg.value = err.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity .2s ease, transform .2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
