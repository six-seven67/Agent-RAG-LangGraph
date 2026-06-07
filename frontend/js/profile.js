/* ============================================================
   Profile Page — 个人信息 + 修改密码
   ============================================================ */

const ProfilePage = (() => {
  let profileData = null;

  async function render() {
    const container = document.getElementById('page-container');
    document.getElementById('navbar').classList.remove('hidden');

    container.innerHTML = `
      <div class="profile-page">
        <h1>👤 个人中心</h1>

        <!-- 基本信息 -->
        <div class="card profile-info" id="profile-info-card">
          <h3 style="margin-bottom:1rem">基本信息</h3>
          <div id="profile-info-content">
            <div class="info-row"><span class="info-label">加载中...</span></div>
          </div>
        </div>

        <!-- 修改邮箱 -->
        <div class="card" style="margin-bottom:1rem">
          <h3 style="margin-bottom:1rem">修改邮箱</h3>
          <form id="email-form">
            <div style="display:flex;gap:0.75rem;align-items:flex-end">
              <div class="form-group flex-1" style="margin-bottom:0">
                <label class="form-label" for="profile-email">新邮箱地址</label>
                <input class="form-input" id="profile-email" type="email" placeholder="newemail@example.com">
              </div>
              <button type="submit" class="btn btn-primary" id="btn-save-email">保存</button>
            </div>
            <div id="email-msg" class="hidden mt-sm"></div>
          </form>
        </div>

        <!-- 修改密码 -->
        <div class="card">
          <h3 style="margin-bottom:1rem">修改密码</h3>
          <form id="password-form">
            <div class="form-group">
              <label class="form-label" for="old-password">当前密码</label>
              <input class="form-input" id="old-password" type="password" placeholder="请输入当前密码" autocomplete="current-password" required>
            </div>
            <div class="form-group">
              <label class="form-label" for="new-password">新密码</label>
              <input class="form-input" id="new-password" type="password" placeholder="6-128字符" autocomplete="new-password" required minlength="6">
            </div>
            <div class="form-group">
              <label class="form-label" for="confirm-password">确认新密码</label>
              <input class="form-input" id="confirm-password" type="password" placeholder="请再次输入新密码" autocomplete="new-password" required>
            </div>
            <div id="password-msg" class="hidden mt-sm"></div>
            <button type="submit" class="btn btn-primary" id="btn-change-pwd">修改密码</button>
          </form>
        </div>
      </div>
    `;

    // 加载个人信息
    await loadProfile();

    // 邮箱表单
    document.getElementById('email-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('profile-email').value.trim();
      const btn = document.getElementById('btn-save-email');
      const msgEl = document.getElementById('email-msg');

      btn.disabled = true;
      btn.textContent = '保存中...';
      msgEl.classList.add('hidden');

      try {
        await API.updateProfile(email || undefined);
        msgEl.textContent = email ? '邮箱更新成功' : '邮箱已清除';
        msgEl.className = 'mt-sm';
        msgEl.style.color = 'var(--color-success)';
        msgEl.classList.remove('hidden');
        // 刷新个人信息
        await loadProfile();
      } catch (err) {
        msgEl.textContent = err.message;
        msgEl.className = 'mt-sm';
        msgEl.style.color = 'var(--color-danger)';
        msgEl.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        btn.textContent = '保存';
      }
    });

    // 密码表单
    document.getElementById('password-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const oldPassword = document.getElementById('old-password').value;
      const newPassword = document.getElementById('new-password').value;
      const confirmPassword = document.getElementById('confirm-password').value;
      const btn = document.getElementById('btn-change-pwd');
      const msgEl = document.getElementById('password-msg');

      if (newPassword !== confirmPassword) {
        msgEl.textContent = '两次新密码输入不一致';
        msgEl.className = 'mt-sm';
        msgEl.style.color = 'var(--color-danger)';
        msgEl.classList.remove('hidden');
        return;
      }
      if (newPassword.length < 6) {
        msgEl.textContent = '新密码至少需要6个字符';
        msgEl.className = 'mt-sm';
        msgEl.style.color = 'var(--color-danger)';
        msgEl.classList.remove('hidden');
        return;
      }

      btn.disabled = true;
      btn.textContent = '修改中...';
      msgEl.classList.add('hidden');

      try {
        const result = await API.changePassword(oldPassword, newPassword);
        msgEl.textContent = result.message || '密码修改成功';
        msgEl.className = 'mt-sm';
        msgEl.style.color = 'var(--color-success)';
        msgEl.classList.remove('hidden');
        // 清空密码字段
        document.getElementById('old-password').value = '';
        document.getElementById('new-password').value = '';
        document.getElementById('confirm-password').value = '';
        Toast.success('密码修改成功');
      } catch (err) {
        msgEl.textContent = err.message;
        msgEl.className = 'mt-sm';
        msgEl.style.color = 'var(--color-danger)';
        msgEl.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        btn.textContent = '修改密码';
      }
    });
  }

  async function loadProfile() {
    const infoContent = document.getElementById('profile-info-content');
    if (!infoContent) return;
    try {
      const data = await API.getProfile();
      profileData = data;
      infoContent.innerHTML = `
        <div class="info-row"><span class="info-label">用户 ID</span><span>${data.id}</span></div>
        <div class="info-row"><span class="info-label">用户名</span><span>${escapeHtml(data.username)}</span></div>
        <div class="info-row"><span class="info-label">邮箱</span><span>${escapeHtml(data.email || '未设置')}</span></div>
        <div class="info-row"><span class="info-label">状态</span><span>${data.is_active ? '✅ 正常' : '🚫 已禁用'}</span></div>
        <div class="info-row"><span class="info-label">注册时间</span><span>${data.created_at || '-'}</span></div>
      `;
      // 回填邮箱到表单
      const emailInput = document.getElementById('profile-email');
      if (emailInput && data.email) {
        emailInput.value = data.email;
      }
    } catch (err) {
      infoContent.innerHTML = `<div class="info-row"><span class="info-label" style="color:var(--color-danger)">加载失败: ${escapeHtml(err.message)}</span></div>`;
    }
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  return { render };
})();
