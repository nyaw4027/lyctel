
/* ============================================================
   LYNCTEL — THEME (DARK/LIGHT)
   ============================================================ */

(function(){
  const STORAGE_KEY = 'lynctel-theme';
  const root = document.documentElement;

  function getTheme() {
    return localStorage.getItem(STORAGE_KEY) ||
      (window.matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
  }

  function applyTheme(theme) {
    root.classList.toggle('dark', theme==='dark');
    localStorage.setItem(STORAGE_KEY, theme);
    // Update all theme toggle icons/labels
    const isDark = theme==='dark';
    document.querySelectorAll('[data-theme-icon]').forEach(el => el.textContent = isDark?'☀️':'🌙');
    document.querySelectorAll('[data-theme-label]').forEach(el => el.textContent = isDark?'Light Mode':'Dark Mode');
  }

  function toggleTheme() {
    const current = root.classList.contains('dark') ? 'dark' : 'light';
    applyTheme(current==='dark' ? 'light' : 'dark');
  }

  // Apply on load (before paint to avoid flash)
  applyTheme(getTheme());

  // Expose
  window.toggleTheme = toggleTheme;
  window.applyTheme  = applyTheme;
})();
