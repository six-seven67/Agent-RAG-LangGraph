/* ============================================================
   Simple Hash Router
   ============================================================ */

const Router = (() => {
  const routes = {};
  let currentRoute = null;
  let beforeNavigate = null;  // guard function: returns false to cancel

  /**
   * 注册路由
   * @param {string} path - 如 '/chat'
   * @param {Function} renderFn - (params) => void
   */
  function on(path, renderFn) {
    routes[path] = renderFn;
  }

  /**
   * 导航到指定 hash
   */
  function navigate(hash) {
    window.location.hash = hash;
  }

  /**
   * 设置导航守卫，返回 false 阻止导航
   */
  function guard(fn) {
    beforeNavigate = fn;
  }

  /**
   * 处理 hash 变化
   */
  function handleRoute() {
    const hash = window.location.hash.slice(1) || '/login';
    const [path, queryString] = hash.split('?');
    const params = {};
    if (queryString) {
      queryString.split('&').forEach(pair => {
        const [k, v] = pair.split('=');
        params[decodeURIComponent(k)] = decodeURIComponent(v || '');
      });
    }

    const renderFn = routes[path];
    if (!renderFn) {
      navigate('/login');
      return;
    }

    // 导航守卫
    if (beforeNavigate) {
      const allowed = beforeNavigate(path);
      if (!allowed) return;
    }

    currentRoute = path;
    renderFn(params);
  }

  /**
   * 启动路由器
   */
  function start() {
    window.addEventListener('hashchange', handleRoute);
    handleRoute(); // 初始加载
  }

  function getCurrentRoute() {
    return currentRoute;
  }

  return { on, navigate, guard, start, getCurrentRoute };
})();
