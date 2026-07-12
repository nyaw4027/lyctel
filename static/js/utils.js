

/* ============================================================
   LYNCTEL — UTILITIES
   ============================================================ */

const L = {
  /* ── DOM ─────────────────────────────────────────── */
  $:  (sel, ctx=document) => ctx.querySelector(sel),
  $$: (sel, ctx=document) => [...ctx.querySelectorAll(sel)],
  on: (el, ev, fn, opts) => el?.addEventListener(ev, fn, opts),

  /* ── Format ─────────────────────────────────────── */
  currency(n, sym='GHS') {
    return `${sym} ${parseFloat(n||0).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',')}`;
  },
  truncate(str, n=40) {
    return str?.length > n ? str.slice(0,n)+'…' : str||'';
  },
  timeAgo(dateStr) {
    const s = Math.floor((Date.now()-new Date(dateStr))/1000);
    if(s<60)   return 'just now';
    if(s<3600) return Math.floor(s/60)+'m ago';
    if(s<86400)return Math.floor(s/3600)+'h ago';
    return Math.floor(s/86400)+'d ago';
  },
  escape(str) {
    return String(str||'')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  /* ── Storage ────────────────────────────────────── */
  store: {
    get(k)    { try{return JSON.parse(localStorage.getItem(k));}catch{return null;} },
    set(k,v)  { try{localStorage.setItem(k,JSON.stringify(v));}catch{} },
    del(k)    { try{localStorage.removeItem(k);}catch{} },
  },

  /* ── Fetch ──────────────────────────────────────── */
  async post(url, data={}, csrf=window.CSRF_TOKEN) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type':'application/json', 'X-CSRFToken':csrf },
      body: JSON.stringify(data),
    });
    return res.json();
  },
  async get(url) {
    const res = await fetch(url);
    return res.json();
  },

  /* ── Toast ──────────────────────────────────────── */
  toast(msg, type='default', duration=3000) {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    const typeClass = {success:'toast-success',error:'toast-error',warning:'toast-warning',gold:'toast-gold'};
    toast.className = `toast ${typeClass[type]||''}`;
    const icons = {success:'✓',error:'✕',warning:'⚠',gold:'★'};
    toast.innerHTML = `<span>${icons[type]||'ℹ'}</span> ${L.escape(msg)}`;
    container.appendChild(toast);
    setTimeout(()=>{ toast.style.opacity='0'; toast.style.transform='translateY(8px)'; toast.style.transition='all .3s'; setTimeout(()=>toast.remove(), 300); }, duration);
  },

  /* ── Debounce ───────────────────────────────────── */
  debounce(fn, ms=300) {
    let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),ms); };
  },
  throttle(fn, ms=300) {
    let last=0; return (...a)=>{ const now=Date.now(); if(now-last>=ms){last=now;fn(...a);} };
  },

  /* ── Clipboard ──────────────────────────────────── */
  async copy(text) {
    try { await navigator.clipboard.writeText(text); L.toast('Copied!','success'); return true; }
    catch { return false; }
  },

  /* ── Device ─────────────────────────────────────── */
  isMobile: () => window.innerWidth < 768,
  isIOS:    () => /iPad|iPhone|iPod/.test(navigator.userAgent),
  isSafari: () => /^((?!chrome|android).)*safari/i.test(navigator.userAgent),
};

window.LUtils = L;
