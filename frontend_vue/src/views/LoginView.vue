<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1>🤖 Agent 智能客服</h1>
      <p class="subtitle">登录您的账号</p>
      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label class="form-label" for="login-username">用户名</label>
          <input class="form-input" id="login-username" v-model="username" type="text"
                 placeholder="请输入用户名" autocomplete="username" required
                 @keydown.enter="handleLogin">
        </div>
        <div class="form-group">
          <label class="form-label" for="login-password">密码</label>
          <input class="form-input" id="login-password" v-model="password" type="password"
                 placeholder="请输入密码" autocomplete="current-password" required
                 @keydown.enter="handleLogin">
        </div>
        <Transition name="fade">
          <div v-if="errorMsg" class="form-error">{{ errorMsg }}</div>
        </Transition>
        <button type="submit" class="btn btn-primary btn-lg" style="width:100%;margin-top:0.5rem"
                :disabled="loading">
          <span v-if="loading" class="typing-indicator" style="display:inline-flex">
            <span></span><span></span><span></span>
          </span>
          <span v-else>登 录</span>
        </button>
      </form>
      <div class="auth-footer">
        还没有账号？<router-link to="/register">立即注册 →</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '../api/index.js'

const router = useRouter()
const username = ref('')
const password = ref('')
const errorMsg = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!username.value.trim() || !password.value) {
    errorMsg.value = '请输入用户名和密码'
    return
  }
  errorMsg.value = ''
  loading.value = true
  try {
    await login(username.value.trim(), password.value)
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
