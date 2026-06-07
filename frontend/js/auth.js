/* ============================================================
   Auth Pages — 登录 + 注册
   ============================================================ */

const AuthPage = (() => {

  /* ---- Login ---- */
  function renderLogin() {
    const container = document.getElementById('page-container');
    document.getElementById('navbar').classList.add('hidden');

    container.innerHTML = `
      <div class="auth-page">
        <div class="auth-card">
          <h1>🤖 RAG 智能客服</h1>
          <p class="subtitle">登录您的账号</p>
          <form id="login-form">
            <div class="form-group">
              <label class="form-label" for="login-username">用户名</label>
              <input class="form-input" id="login-username" type="text" placeholder="请输入用户名" autocomplete="username" required>
            </div>
            <div class="form-group">
              <label class="form-label" for="login-password">密码</label>
              <input class="form-input" id="login-password" type="password" placeholder="请输入密码" autocomplete="current-password" required>
            </div>
            <div id="login-error" class="form-error hidden"></div>
            <button type="submit" class="btn btn-primary btn-lg" style="width:100%;margin-top:0.5rem" id="login-btn">登 录</button>
          </form>
          <div class="auth-footer">
            还没有账号？<a href="#/register">立即注册 →</a>
          </div>
        </div>
      </div>
    `;

    document.getElementById('login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = document.getElementById('login-username').value.trim();
      const password = document.getElementById('login-password').value;
      const errorEl = document.getElementById('login-error');
      const btn = document.getElementById('login-btn');

      if (!username || !password) {
        errorEl.textContent = '请输入用户名和密码';
        errorEl.classList.remove('hidden');
        return;
      }

      errorEl.classList.add('hidden');
      btn.disabled = true;
      btn.textContent = '登录中...';

      try {
        await API.login(username, password);
        Router.navigate('/chat');
      } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        btn.textContent = '登 录';
      }
    });
  }

  /* ---- Register ---- */
  function renderRegister() {
    const container = document.getElementById('page-container');
    document.getElementById('navbar').classList.add('hidden');

    container.innerHTML = `
      <div class="auth-page">
        <div class="auth-card">
          <h1>📝 注册新账号</h1>
          <p class="subtitle">加入 RAG 智能客服系统</p>
          <form id="register-form">
            <div class="form-group">
              <label class="form-label" for="reg-username">用户名 <span style="color:var(--color-danger)">*</span></label>
              <input class="form-input" id="reg-username" type="text" placeholder="2-50字符，支持字母/数字/下划线/中文" autocomplete="username" required>
            </div>
            <div class="form-group">
              <label class="form-label" for="reg-email">邮箱 <span class="text-secondary">(选填)</span></label>
              <input class="form-input" id="reg-email" type="email" placeholder="example@mail.com" autocomplete="email">
            </div>
            <div class="form-group">
              <label class="form-label" for="reg-password">密码 <span style="color:var(--color-danger)">*</span></label>
              <input class="form-input" id="reg-password" type="password" placeholder="6-128字符" autocomplete="new-password" required>
            </div>
            <div class="form-group">
              <label class="form-label" for="reg-password2">确认密码 <span style="color:var(--color-danger)">*</span></label>
              <input class="form-input" id="reg-password2" type="password" placeholder="请再次输入密码" autocomplete="new-password" required>
            </div>
            <div id="reg-error" class="form-error hidden"></div>
            <button type="submit" class="btn btn-primary btn-lg" style="width:100%;margin-top:0.5rem" id="reg-btn">注 册</button>
          </form>
          <div class="auth-footer">
            已有账号？<a href="#/login">立即登录 →</a>
          </div>
        </div>
      </div>
    `;

    document.getElementById('register-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = document.getElementById('reg-username').value.trim();
      const email = document.getElementById('reg-email').value.trim();
      const password = document.getElementById('reg-password').value;
      const password2 = document.getElementById('reg-password2').value;
      const errorEl = document.getElementById('reg-error');
      const btn = document.getElementById('reg-btn');

      // 前端校验
      if (!username || !password) {
        errorEl.textContent = '用户名和密码为必填项';
        errorEl.classList.remove('hidden');
        return;
      }
      if (password !== password2) {
        errorEl.textContent = '两次密码输入不一致';
        errorEl.classList.remove('hidden');
        return;
      }
      if (password.length < 6) {
        errorEl.textContent = '密码至少需要6个字符';
        errorEl.classList.remove('hidden');
        return;
      }

      errorEl.classList.add('hidden');
      btn.disabled = true;
      btn.textContent = '注册中...';

      try {
        await API.register(username, password, email || undefined);
        Router.navigate('/chat');
      } catch (err) {
        errorEl.textContent = err.message;
        errorEl.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        btn.textContent = '注 册';
      }
    });
  }

  return { renderLogin, renderRegister };
})();
