/* ============================================================
   App — 启动 + 路由注册 + 导航守卫 + Toast + 全局事件
   ============================================================ */

(function () {
  'use strict';

  // ========== Toast System ==========
  window.Toast = {
    show(message, type = 'info', duration = 3500) {
      const container = document.getElementById('toast-container');
      const el = document.createElement('div');
      el.className = `toast toast-${type}`;
      el.textContent = message;
      container.appendChild(el);
      setTimeout(() => {
        el.style.opacity = '0';
        el.style.transition = 'opacity 0.3s';
        setTimeout(() => el.remove(), 300);
      }, duration);
    },
    success(msg) { this.show(msg, 'success'); },
    error(msg) { this.show(msg, 'error'); },
    info(msg) { this.show(msg, 'info'); },
  };

  // ========== Route Guard ==========
  // 需要登录的页面
  const protectedRoutes = ['/chat', '/knowledge', '/profile'];

  // 不需要登录就能访问的页面
  const publicRoutes = ['/login', '/register'];

  function isAuthenticated() {
    return !!(API.getAccessToken() || API.getRefreshToken());
  }

  Router.guard((path) => {
    if (protectedRoutes.includes(path) && !isAuthenticated()) {
      // 未登录 → 跳转登录页
      Router.navigate('/login');
      return false;
    }
    if (publicRoutes.includes(path) && isAuthenticated()) {
      // 已登录 → 跳转对话页
      Router.navigate('/chat');
      return false;
    }
    return true;
  });

  // ========== Register Routes ==========
  Router.on('/login', AuthPage.renderLogin);
  Router.on('/register', AuthPage.renderRegister);
  Router.on('/chat', ChatPage.render);
  Router.on('/knowledge', KnowledgePage.render);
  Router.on('/profile', ProfilePage.render);

  // Default redirect
  Router.on('/', () => {
    if (isAuthenticated()) Router.navigate('/chat');
    else Router.navigate('/login');
  });

  // ========== Navbar Active Link ==========
  window.addEventListener('hashchange', updateNavActive);
  function updateNavActive() {
    const current = Router.getCurrentRoute();
    document.querySelectorAll('.nav-link').forEach(link => {
      link.classList.toggle('active', link.dataset.route === current);
    });
  }

  // ========== Global Logout Button ==========
  document.getElementById('btn-logout').addEventListener('click', async () => {
    if (!confirm('确定要退出登录吗？')) return;
    try {
      await API.logout();
    } catch { /* ignore */ }
    Router.navigate('/login');
    Toast.info('已退出登录');
  });

  // ========== Auto-restore Token on App Start ==========
  async function initAuth() {
    const rt = API.getRefreshToken();
    if (rt && !API.getAccessToken()) {
      // 有 refresh_token 但没有 access_token → 自动刷新
      try {
        await API.refreshAccessToken();
      } catch {
        API.clearTokens();
      }
    }
  }

  // ========== Boot ==========
  async function boot() {
    await initAuth();
    Router.start();
    updateNavActive();
    console.log('🚀 Agent 智能客服系统前端已启动 (v3.0.0)');
    console.log('   Base URL: http://localhost:8000');
    console.log('   当前路由:', isAuthenticated() ? '已登录' : '未登录');
  }

  // DOM 加载完成后启动
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
