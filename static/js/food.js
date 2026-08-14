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




/**
 * food.js — Food cart JavaScript for Lynctel Food
 *
 * Exposes a single global Food object with:
 *   Food.init()        — call on DOMContentLoaded
 *   Food.addToCart(pk) — add a food menu item to the food cart
 *
 * The food cart is separate from the main e-commerce cart.
 * It lives at /food/cart/ and uses food-specific endpoints.
 *
 * Endpoints used:
 *   POST /food/cart/add/{item_id}/   → add item
 *   POST /food/cart/update/{item_id}/→ update quantity
 *   GET  /food/cart/data/            → get cart state (count + total)
 */

'use strict';

const Food = (function () {

  // ── Helpers ───────────────────────────────────────────────
  function getCsrf() {
    // base.html exposes CSRF_TOKEN globally
    return (typeof CSRF_TOKEN !== 'undefined' ? CSRF_TOKEN : null) ||
      document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  }

  function isAuthenticated() {
    return typeof IS_AUTHENTICATED !== 'undefined' && IS_AUTHENTICATED;
  }

  function getLoginUrl() {
    return (typeof LOGIN_URL !== 'undefined' ? LOGIN_URL : '/accounts/login/');
  }

  // ── Toast notification ────────────────────────────────────
  let toastEl = null;
  let toastTimer = null;

  function showToast(message, type) {
    // type: 'success' | 'error' | 'warning' | 'info'
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.id = 'food-toast';
      toastEl.style.cssText = [
        'position:fixed',
        'bottom:80px',
        'left:50%',
        'transform:translateX(-50%)',
        'z-index:9999',
        'padding:12px 20px',
        'border-radius:14px',
        'font-size:13px',
        'font-weight:600',
        'color:white',
        'box-shadow:0 8px 24px rgba(0,0,0,.25)',
        'transition:opacity .3s,transform .3s',
        'pointer-events:none',
        'white-space:nowrap',
        'max-width:calc(100vw - 32px)',
        'text-align:center',
      ].join(';');
      document.body.appendChild(toastEl);
    }

    const colors = {
      success: '#16a34a',
      error:   '#dc2626',
      warning: '#d97706',
      info:    '#0F1B2D',
    };
    toastEl.style.background  = colors[type] || colors.info;
    toastEl.textContent        = message;
    toastEl.style.opacity      = '1';
    toastEl.style.transform    = 'translateX(-50%) translateY(0)';

    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.style.opacity   = '0';
      toastEl.style.transform = 'translateX(-50%) translateY(8px)';
    }, 2800);
  }

  // ── Cart badge update ─────────────────────────────────────
  // The food cart has its own badge separate from the main e-commerce cart.
  function updateFoodBadge(count) {
    document.querySelectorAll('[data-food-cart-count]').forEach(function (el) {
      el.textContent = count;
      el.style.display = count > 0 ? 'flex' : 'none';
    });
  }

  // ── Add to cart ───────────────────────────────────────────
  /**
   * addToCart(itemPk)
   *
   * POSTs to /food/cart/add/{itemPk}/ to add one unit of a menu item.
   * Shows button feedback and a toast notification.
   *
   * @param {number} itemPk - The primary key of the FoodItem to add.
   */
  function addToCart(itemPk) {
    if (!isAuthenticated()) {
      var next = encodeURIComponent(window.location.pathname);
      window.location.href = getLoginUrl() + '?next=' + next;
      return;
    }

    var csrf = getCsrf();
    if (!csrf) {
      showToast('Session error — please refresh the page', 'error');
      return;
    }

    // Visual feedback — find all cards/buttons for this item and dim them
    var cards = document.querySelectorAll('[data-food-item="' + itemPk + '"]');
    cards.forEach(function (card) {
      card.style.opacity = '0.6';
      card.style.pointerEvents = 'none';
    });

    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', csrf);
    fd.append('quantity', 1);

    fetch('/food/cart/add/' + itemPk + '/', {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body:    fd,
    })
      .then(function (res) {
        if (res.status === 403) throw new Error('auth');
        if (!res.ok) throw new Error('server');
        return res.json();
      })
      .then(function (data) {
        if (data.success || data.cart_count !== undefined) {
          showToast('✓ Added to cart', 'success');
          updateFoodBadge(data.cart_count || 0);

          // Pulse animation on cart icon
          document.querySelectorAll('[data-food-cart-icon]').forEach(function (el) {
            el.classList.add('food-cart-pop');
            setTimeout(function () { el.classList.remove('food-cart-pop'); }, 400);
          });
        } else if (data.error) {
          showToast(data.error, 'warning');
        } else if (data.conflict) {
          // Different restaurant already in cart
          showToast('⚠ Clear your cart first to order from here', 'warning');
        } else {
          showToast('Could not add item — try again', 'error');
        }
      })
      .catch(function (err) {
        if (err.message === 'auth') {
          window.location.href = getLoginUrl() + '?next=' + encodeURIComponent(window.location.pathname);
        } else {
          showToast('Network error — check your connection', 'error');
        }
      })
      .finally(function () {
        cards.forEach(function (card) {
          card.style.opacity = '';
          card.style.pointerEvents = '';
        });
      });
  }

  // ── Fetch cart state on load ──────────────────────────────
  function fetchCartState() {
    if (!isAuthenticated()) return;
    fetch('/food/cart/data/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        updateFoodBadge(data.cart_count || data.count || 0);
      })
      .catch(function () {});
  }

  // ── Cart page: inline update/remove ──────────────────────
  // On the food cart page, quantity steppers update via AJAX
  // instead of full form POST for a better UX.
  function initCartPage() {
    var isCartPage = document.querySelector('[data-food-cart-page]');
    if (!isCartPage) return;

    document.querySelectorAll('[data-food-update-form]').forEach(function (form) {
      var input   = form.querySelector('input[type="number"]');
      var itemPk  = form.dataset.itemPk;
      if (!input || !itemPk) return;

      // Attach stepper buttons if present
      var minusBtn = form.querySelector('[data-minus]');
      var plusBtn  = form.querySelector('[data-plus]');

      if (minusBtn) {
        minusBtn.addEventListener('click', function () {
          var v = parseInt(input.value, 10) || 1;
          if (v <= 1) {
            removeItem(itemPk, form.closest('[data-food-item-row]'));
          } else {
            input.value = v - 1;
            updateItem(itemPk, v - 1);
          }
        });
      }
      if (plusBtn) {
        plusBtn.addEventListener('click', function () {
          var v = parseInt(input.value, 10) || 1;
          input.value = v + 1;
          updateItem(itemPk, v + 1);
        });
      }

      input.addEventListener('change', function () {
        var v = parseInt(input.value, 10) || 0;
        if (v <= 0) {
          removeItem(itemPk, form.closest('[data-food-item-row]'));
        } else {
          updateItem(itemPk, v);
        }
      });
    });

    document.querySelectorAll('[data-food-remove-btn]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var row    = btn.closest('[data-food-item-row]');
        var itemPk = btn.dataset.foodRemoveBtn;
        removeItem(itemPk, row);
      });
    });
  }

  function updateItem(itemPk, quantity) {
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fd.append('quantity', quantity);
    fetch('/food/cart/update/' + itemPk + '/', {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body:    fd,
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        updateFoodBadge(data.cart_count || data.count || 0);
        if (data.new_total !== undefined) {
          var totalEl = document.querySelector('[data-item-total="' + itemPk + '"]');
          if (totalEl) totalEl.textContent = 'GHS ' + parseFloat(data.new_total).toFixed(2);
        }
        refreshCartSummary();
      })
      .catch(function () { showToast('Update failed — try again', 'error'); });
  }

  function removeItem(itemPk, row) {
    if (row) {
      row.style.opacity     = '0.4';
      row.style.transition  = 'opacity .25s';
    }
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fd.append('quantity', 0); // quantity=0 means remove
    fetch('/food/cart/update/' + itemPk + '/', {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body:    fd,
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (row) row.remove();
        updateFoodBadge(data.cart_count || data.count || 0);
        refreshCartSummary();
        // Show empty state if no items left
        var remaining = document.querySelectorAll('[data-food-item-row]');
        if (remaining.length === 0) {
          var emptyEl = document.querySelector('[data-food-cart-empty]');
          var listEl  = document.querySelector('[data-food-cart-list]');
          if (emptyEl) emptyEl.style.display = 'block';
          if (listEl)  listEl.style.display  = 'none';
          var checkoutBtn = document.querySelector('[data-food-checkout-btn]');
          if (checkoutBtn) checkoutBtn.style.display = 'none';
        }
      })
      .catch(function () {
        if (row) { row.style.opacity = ''; }
        showToast('Remove failed — try again', 'error');
      });
  }

  function refreshCartSummary() {
    fetch('/food/cart/data/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        updateFoodBadge(data.cart_count || data.count || 0);
        var subtotalEl  = document.querySelector('[data-cart-subtotal]');
        var deliveryEl  = document.querySelector('[data-cart-delivery]');
        var totalEl     = document.querySelector('[data-cart-total]');
        if (subtotalEl) subtotalEl.textContent = 'GHS ' + parseFloat(data.subtotal  || 0).toFixed(2);
        if (deliveryEl) deliveryEl.textContent = 'GHS ' + parseFloat(data.delivery  || 0).toFixed(2);
        if (totalEl)    totalEl.textContent    = 'GHS ' + parseFloat(data.total     || 0).toFixed(2);
      })
      .catch(function () {});
  }

  // ── Menu: category scroll spy ─────────────────────────────
  function initScrollSpy() {
    var sections = document.querySelectorAll('section[id^="cat-"]');
    var catBtns  = document.querySelectorAll('.food-cat-btn');
    if (!sections.length || !catBtns.length) return;

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var id = entry.target.id;
          catBtns.forEach(function (btn) {
            var href = btn.getAttribute('href');
            btn.classList.toggle(
              'active',
              href && href === '#' + id
            );
          });
        });
      },
      { rootMargin: '-30% 0px -60% 0px', threshold: 0 }
    );

    sections.forEach(function (s) { observer.observe(s); });
  }

  // ── Animate cards on scroll ───────────────────────────────
  function initFadeIn() {
    if (!('IntersectionObserver' in window)) return;
    var cards = document.querySelectorAll('.menu-item-card');
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.style.opacity   = '1';
            entry.target.style.transform = 'translateY(0)';
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1 }
    );
    cards.forEach(function (card, i) {
      card.style.opacity    = '0';
      card.style.transform  = 'translateY(12px)';
      card.style.transition = 'opacity .35s ease ' + (i * 0.04) + 's, transform .35s ease ' + (i * 0.04) + 's';
      observer.observe(card);
    });
  }

  // ── Public init ───────────────────────────────────────────
  function init() {
    fetchCartState();
    initCartPage();
    initScrollSpy();
    initFadeIn();
  }

  return {
    init:       init,
    addToCart:  addToCart,
    showToast:  showToast,
  };

})();

// Add cart pop animation CSS once
(function () {
  var style = document.createElement('style');
  style.textContent = [
    '@keyframes foodCartPop{0%,100%{transform:scale(1)}50%{transform:scale(1.4)}}',
    '.food-cart-pop{animation:foodCartPop .4s ease}',
  ].join('');
  document.head.appendChild(style);
})();