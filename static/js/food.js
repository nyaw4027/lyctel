/* static/js/food.js — consolidated food app client JS
   Exposes a global Food object with init() and addToCart(id) helpers.
   Minimal footprint and defensive operations.
*/
window.Food = (function(){
  const CSRF = (function(){ try { return JSON.parse(JSON.stringify(document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '{{ csrf_token }}')); } catch(e){ return '{{ csrf_token }}'; } })();

  let cartCount = 0, cartTotal = 0, pendingItemId = null;

  function qs(s){ return document.querySelector(s); }
  function qsa(s){ return Array.from(document.querySelectorAll(s)); }

  function setCartBar(count, total){
    cartCount = count || 0;
    cartTotal = total || 0;
    const bar = qs('#cart-bar');
    const countEl = qs('#cart-bar-count');
    const totalEl = qs('#cart-bar-total');
    if(countEl) countEl.textContent = cartCount;
    if(totalEl) totalEl.textContent = 'GHS ' + (cartTotal||0).toFixed(2);
    if(bar) {
      bar.classList.toggle('d-none', cartCount <= 0);
    }
  }

  async function fetchCartData(){
    try {
      const res = await fetch('/food/cart/data/', { headers: {'X-Requested-With':'XMLHttpRequest'} });
      const d = await res.json();
      if(d && d.success) setCartBar(d.count||0, parseFloat(d.total||0));
    } catch(e){}
  }

  async function addToCart(itemId, opts){
    opts = opts || {};
    // If user not logged in, server-side template redirects; we keep the guard lightweight
    try {
      const res = await fetch(`/food/cart/add/${itemId}/`, {
        method:'POST',
        headers: {'Content-Type':'application/json','X-CSRFToken':CSRF,'X-Requested-With':'XMLHttpRequest'},
        body: JSON.stringify({ quantity: 1 })
      });
      const d = await res.json();
      if(d.conflict){
        pendingItemId = itemId;
        showConflictModal(d.message || 'You have items from another vendor in cart.');
        return;
      }
      if(d.success){
        setCartBar(d.cart_count||0, parseFloat(d.cart_total||0));
        const btn = qs(`#add-btn-${itemId}`);
        if(btn){
          const orig = btn.textContent;
          btn.textContent = '✓';
          btn.classList.add('btn-press');
          setTimeout(()=>{ btn.textContent = orig; btn.classList.remove('btn-press'); }, 900);
        }
      }
    } catch(e){ console.warn('addToCart error', e); }
  }

  function showConflictModal(message){
    const modal = qs('#conflict-modal');
    if(!modal) return;
    const msg = qs('#conflict-msg');
    if(msg) msg.textContent = message;
    modal.classList.remove('d-none');
  }

  function closeConflict(){
    const modal = qs('#conflict-modal');
    if(modal) modal.classList.add('d-none');
    pendingItemId = null;
  }

  async function confirmClear(){
    try {
      await fetch('/food/cart/clear/', { method:'POST', headers: {'X-Requested-With':'XMLHttpRequest','X-CSRFToken':CSRF}});
      if(pendingItemId) await addToCart(pendingItemId);
      closeConflict();
    } catch(e){ console.warn(e); }
  }

  // Sticky category highlight
  function bindCategoryScroll(){
    const sections = qsa('[id^="cat-"]');
    const navLinks = qsa('.food-cat-btn');
    if(!sections.length || !navLinks.length) return;
    function onScroll(){
      let current = '';
      sections.forEach(s => { if(window.scrollY + 120 >= s.offsetTop) current = s.id; });
      navLinks.forEach(a => a.classList.toggle('active', a.getAttribute('href') === `#${current}`));
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  function preserveScroll(){
    try {
      const key = 'food_home_scroll_v2';
      const stored = sessionStorage.getItem(key);
      if(stored) window.scrollTo(0, parseInt(stored,10) || 0);
      window.addEventListener('beforeunload', ()=> sessionStorage.setItem(key, window.scrollY || 0));
    } catch(e){}
  }

  function init(){
    fetchCartData();
    bindCategoryScroll();
    preserveScroll();
    // hook modal buttons if present
    const keepBtn = qs('#conflict-modal .btn-outline-secondary');
    const clearBtn = qs('#conflict-modal .btn-navy');
    if(keepBtn) keepBtn.addEventListener('click', (e)=>{ closeConflict(); });
    if(clearBtn) clearBtn.addEventListener('click', (e)=>{ confirmClear(); });
    // Expose helper on window for inline onclick use
    window.Food = window.Food || {};
    window.Food.addToCart = addToCart;
  }

  return { init, addToCart, _fetchCartData: fetchCartData };
})();