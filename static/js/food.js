/**
 * food.js — Lynctel Food unified cart + menu JS
 *
 * FIXES in this version:
 *   1. Hardcoded /food/cart/* URLs replaced with window.FOOD_* globals
 *      set by menu.html/cart.html — works regardless of URL mount path.
 *   2. #cart-bar element is now injected by food.js itself so it always
 *      exists even if the template doesn't include it.
 *   3. 302 redirect detection — @login_required AJAX redirects now
 *      correctly route to the login page instead of throwing a JSON error.
 *   4. console.error logging added to every failure path for debugging.
 *   5. All silent failures now show a visible toast.
 */

window.Food = (function () {
  'use strict';

  // ── URL resolution ────────────────────────────────────────
  // Set by the template before this script loads (see menu.html extra_js).
  // Fallback to conventional paths so the file still works if globals
  // are missing (e.g. when testing directly).
  function url(key, fallback) {
    return (typeof window[key] !== 'undefined' && window[key]) ? window[key] : fallback;
  }
  function cartAddUrl(id)    { return url('FOOD_CART_ADD_URL',    '/food/cart/add/')    + id + '/'; }
  function cartUpdateUrl(id) { return url('FOOD_CART_UPDATE_URL', '/food/cart/update/') + id + '/'; }
  function cartClearUrl()    { return url('FOOD_CART_CLEAR_URL',  '/food/cart/clear/'); }
  function cartDataUrl()     { return url('FOOD_CART_DATA_URL',   '/food/cart/data/'); }
  function loginUrl()        { return url('LOGIN_URL',            '/accounts/login/'); }

  // ── Auth helpers ──────────────────────────────────────────
  function getCsrf() {
    if (typeof CSRF_TOKEN !== 'undefined' && CSRF_TOKEN) return CSRF_TOKEN;
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }
  function isAuth() {
    return typeof IS_AUTHENTICATED !== 'undefined' && IS_AUTHENTICATED;
  }

  // ── Toast ─────────────────────────────────────────────────
  var _toastEl = null, _toastTimer = null;

  function showToast(msg, type) {
    if (!_toastEl) {
      _toastEl = document.createElement('div');
      _toastEl.id = 'food-toast';
      Object.assign(_toastEl.style, {
        position: 'fixed', bottom: '80px', left: '50%',
        transform: 'translateX(-50%) translateY(0)',
        zIndex: '9999', padding: '12px 22px', borderRadius: '14px',
        fontSize: '13px', fontWeight: '600', color: 'white',
        boxShadow: '0 8px 24px rgba(0,0,0,.25)',
        transition: 'opacity .3s, transform .3s',
        pointerEvents: 'none', whiteSpace: 'nowrap',
        maxWidth: 'calc(100vw - 32px)', textAlign: 'center', opacity: '0',
      });
      document.body.appendChild(_toastEl);
    }
    var colors = { success: '#16a34a', error: '#dc2626', warning: '#d97706', info: '#0F1B2D' };
    _toastEl.style.background = colors[type] || colors.info;
    _toastEl.textContent = msg;
    _toastEl.style.opacity = '1';
    _toastEl.style.transform = 'translateX(-50%) translateY(0)';
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () {
      _toastEl.style.opacity = '0';
      _toastEl.style.transform = 'translateX(-50%) translateY(8px)';
    }, 2800);
  }

  // ── #cart-bar (floating bar) ──────────────────────────────
  // Inject if missing so templates don't have to include it explicitly.
  function ensureCartBar() {
    if (document.getElementById('cart-bar')) return;
    var bar = document.createElement('div');
    bar.id = 'cart-bar';
    bar.className = 'd-none';
    bar.style.cssText = (
      'position:fixed;bottom:16px;left:50%;transform:translateX(-50%);' +
      'background:#0F1B2D;color:white;border-radius:14px;padding:12px 20px;' +
      'display:flex;align-items:center;gap:14px;z-index:1000;' +
      'box-shadow:0 8px 24px rgba(0,0,0,.3);min-width:200px;' +
      'font-weight:600;font-size:.9rem;cursor:pointer;'
    );
    bar.innerHTML = (
      '<span>🛒 <span id="cart-bar-count">0</span> item(s)</span>' +
      '<span style="opacity:.6">|</span>' +
      '<span id="cart-bar-total">GHS 0.00</span>' +
      '<a id="cart-bar-link" href="' + url('FOOD_CART_URL', '/food/cart/') + '" ' +
         'style="color:#F5A623;text-decoration:none;font-size:.85rem">View →</a>'
    );
    document.body.appendChild(bar);
  }

  // ── Cart UI update ────────────────────────────────────────
  function updateCartUI(count, total) {
    count = parseInt(count, 10) || 0;
    total = parseFloat(total) || 0;

    var bar      = document.getElementById('cart-bar');
    var countEl  = document.getElementById('cart-bar-count');
    var totalEl  = document.getElementById('cart-bar-total');

    if (countEl) countEl.textContent = count;
    if (totalEl) totalEl.textContent = 'GHS ' + total.toFixed(2);
    if (bar) {
      if (count > 0) {
        bar.classList.remove('d-none');
        bar.style.display = 'flex';
      } else {
        bar.classList.add('d-none');
        bar.style.display = '';
      }
    }

    // Also update any badge elements in the nav
    document.querySelectorAll('[data-food-cart-count]').forEach(function (el) {
      el.textContent = count;
      el.style.display = count > 0 ? 'flex' : 'none';
    });
  }

  // ── Conflict modal ────────────────────────────────────────
  var _pendingItemId = null;

  function showConflict(message) {
    var modal = document.getElementById('conflict-modal');
    if (modal) {
      var msgEl = document.getElementById('conflict-msg');
      if (msgEl) msgEl.textContent = message || 'You have items from another restaurant.';
      modal.classList.remove('d-none');
    } else {
      showToast('⚠ ' + (message || 'Clear your cart first'), 'warning');
    }
  }

  function closeConflict() {
    var modal = document.getElementById('conflict-modal');
    if (modal) modal.classList.add('d-none');
    _pendingItemId = null;
  }

  function confirmClear() {
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fetch(cartClearUrl(), {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
    })
    .then(function () {
      var id = _pendingItemId;
      closeConflict();
      if (id) addToCart(id);
    })
    .catch(function (e) {
      console.error('[Food] confirmClear failed:', e);
      showToast('Could not clear cart — try again', 'error');
    });
  }

  // ── Fetch current cart state ──────────────────────────────
  function fetchCartState() {
    if (!isAuth()) return;
    fetch(cartDataUrl(), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (d) {
      updateCartUI(d.count || d.cart_count || 0, d.total || d.cart_total || 0);
    })
    .catch(function (e) {
      console.warn('[Food] fetchCartState failed:', e);
    });
  }

  // ── Add to cart (main action) ─────────────────────────────
  function addToCart(itemId, qty) {
    qty = qty || 1;

    // Not logged in → redirect to login
    if (!isAuth()) {
      window.location.href = loginUrl() + '?next=' + encodeURIComponent(window.location.pathname);
      return;
    }

    var csrf = getCsrf();
    if (!csrf) {
      console.error('[Food] No CSRF token — is base.html loaded?');
      showToast('Session error — please refresh the page', 'error');
      return;
    }

    // Visual feedback: dim the card
    var cards = document.querySelectorAll('[data-food-item="' + itemId + '"]');
    cards.forEach(function (c) {
      c.style.opacity       = '0.5';
      c.style.pointerEvents = 'none';
    });

    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', csrf);
    fd.append('quantity', qty);

    fetch(cartAddUrl(itemId), {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body:    fd,
    })
    .then(function (res) {
      // Detect redirect to login (302 → login page HTML, not JSON)
      if (res.redirected || res.url.indexOf('login') !== -1) {
        window.location.href = loginUrl() + '?next=' + encodeURIComponent(window.location.pathname);
        return null;
      }
      if (res.status === 403) {
        // CSRF failure
        showToast('Security check failed — please refresh', 'error');
        console.error('[Food] 403 on cart_add — CSRF mismatch');
        return null;
      }
      if (!res.ok) {
        console.error('[Food] cart_add returned HTTP', res.status);
        showToast('Server error (' + res.status + ') — try again', 'error');
        return null;
      }
      return res.json();
    })
    .then(function (d) {
      if (!d) return;
      if (d.conflict) {
        _pendingItemId = itemId;
        showConflict(d.message);
        return;
      }
      if (d.success || d.cart_count !== undefined) {
        updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
        showToast('✓ Added to cart', 'success');
        // Flash the + button
        var btn = document.getElementById('add-btn-' + itemId);
        if (btn) {
          var orig = btn.textContent;
          btn.textContent = '✓';
          setTimeout(function () { btn.textContent = orig; }, 900);
        }
        // Animate cart-bar
        var bar = document.getElementById('cart-bar');
        if (bar) {
          bar.style.transform = 'translateX(-50%) scale(1.06)';
          setTimeout(function () { bar.style.transform = 'translateX(-50%) scale(1)'; }, 200);
        }
      } else {
        console.warn('[Food] Unexpected cart_add response:', d);
        showToast(d.error || 'Could not add item', 'warning');
      }
    })
    .catch(function (e) {
      console.error('[Food] addToCart fetch error:', e);
      showToast('Could not connect — check your internet', 'error');
    })
    .finally(function () {
      cards.forEach(function (c) {
        c.style.opacity       = '';
        c.style.pointerEvents = '';
      });
    });
  }

  // ── Cart page: stepper + AJAX remove ─────────────────────
  function initCartPage() {
    if (!document.querySelector('[data-food-cart-page], [data-food-cart-list]')) return;

    // Stepper forms
    document.querySelectorAll('[data-food-update-form]').forEach(function (form) {
      var input  = form.querySelector('input[type="number"]');
      var itemPk = form.dataset.itemPk;
      if (!input || !itemPk) return;

      form.querySelector('[data-minus]') && form.querySelector('[data-minus]')
        .addEventListener('click', function () {
          var v = parseInt(input.value, 10) || 1;
          if (v <= 1) {
            cartRemoveItem(itemPk, form.closest('[data-food-item-row]'));
          } else {
            input.value = v - 1;
            cartUpdateItem(itemPk, v - 1);
          }
        });

      form.querySelector('[data-plus]') && form.querySelector('[data-plus]')
        .addEventListener('click', function () {
          var v = parseInt(input.value, 10) || 1;
          input.value = v + 1;
          cartUpdateItem(itemPk, v + 1);
        });

      input.addEventListener('change', function () {
        var v = parseInt(input.value, 10) || 0;
        if (v <= 0) cartRemoveItem(itemPk, form.closest('[data-food-item-row]'));
        else        cartUpdateItem(itemPk, v);
      });
    });

    // Remove buttons
    document.querySelectorAll('[data-food-remove-btn]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        cartRemoveItem(btn.dataset.foodRemoveBtn, btn.closest('[data-food-item-row]'));
      });
    });
  }

  function cartUpdateItem(itemPk, quantity) {
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fd.append('quantity', quantity);
    fetch(cartUpdateUrl(itemPk), {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body:    fd,
    })
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (d) {
      updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
      if (d.new_total !== undefined) {
        var el = document.querySelector('[data-item-total="' + itemPk + '"]');
        if (el) el.textContent = 'GHS ' + parseFloat(d.new_total).toFixed(2);
      }
      refreshCartSummary();
    })
    .catch(function (e) {
      console.error('[Food] cartUpdateItem failed:', e);
      showToast('Update failed — try again', 'error');
    });
  }

  function cartRemoveItem(itemPk, row) {
    if (row) row.style.opacity = '0.4';
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fd.append('quantity', 0);
    fetch(cartUpdateUrl(itemPk), {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body:    fd,
    })
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (d) {
      if (row) row.remove();
      updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
      refreshCartSummary();
      if (!document.querySelectorAll('[data-food-item-row]').length) {
        var empty = document.querySelector('[data-food-cart-empty]');
        var list  = document.querySelector('[data-food-cart-list]');
        var btn   = document.querySelector('[data-food-checkout-btn]');
        if (empty) empty.style.removeProperty('display');
        if (list)  list.style.display  = 'none';
        if (btn)   btn.style.display   = 'none';
      }
    })
    .catch(function (e) {
      if (row) row.style.opacity = '';
      console.error('[Food] cartRemoveItem failed:', e);
      showToast('Remove failed — try again', 'error');
    });
  }

  function refreshCartSummary() {
    fetch(cartDataUrl(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      updateCartUI(d.count || d.cart_count || 0, d.total || d.cart_total || 0);
      var sub = document.querySelector('[data-cart-subtotal]');
      var del = document.querySelector('[data-cart-delivery]');
      var tot = document.querySelector('[data-cart-total]');
      if (sub) sub.textContent = 'GHS ' + parseFloat(d.subtotal || d.total || 0).toFixed(2);
      if (del) del.textContent = 'GHS ' + parseFloat(d.delivery || 0).toFixed(2);
      if (tot) tot.textContent = 'GHS ' + parseFloat(d.total    || 0).toFixed(2);
    })
    .catch(function (e) { console.warn('[Food] refreshCartSummary failed:', e); });
  }

  // ── Category scroll spy ───────────────────────────────────
  function initScrollSpy() {
    var sections = document.querySelectorAll('section[id^="cat-"]');
    var catBtns  = document.querySelectorAll('.food-cat-btn');
    if (!sections.length || !catBtns.length) return;

    if ('IntersectionObserver' in window) {
      var obs = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          catBtns.forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('href') === '#' + entry.target.id);
          });
        });
      }, { rootMargin: '-30% 0px -60% 0px', threshold: 0 });
      sections.forEach(function (s) { obs.observe(s); });
    }
  }

  // ── Fade-in for menu cards ────────────────────────────────
  function initFadeIn() {
    if (!('IntersectionObserver' in window)) return;
    var cards = document.querySelectorAll('.menu-item-card');
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.style.opacity    = '1';
          entry.target.style.transform  = 'translateY(0)';
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });
    cards.forEach(function (card, i) {
      card.style.opacity   = '0';
      card.style.transform = 'translateY(12px)';
      card.style.transition = 'opacity .35s ease ' + (i * 0.04) + 's, transform .35s ease ' + (i * 0.04) + 's';
      obs.observe(card);
    });
  }

  // ── Main init ─────────────────────────────────────────────
  function init() {
    ensureCartBar();     // inject #cart-bar if template doesn't have it
    fetchCartState();    // populate badge + cart-bar on page load
    initCartPage();      // wire stepper + remove buttons
    initScrollSpy();     // category nav highlight
    initFadeIn();        // subtle scroll animations

    // Conflict modal buttons
    var keepBtn  = document.querySelector('#conflict-modal .btn-keep');
    var clearBtn = document.querySelector('#conflict-modal .btn-clear');
    if (keepBtn)  keepBtn.addEventListener('click',  closeConflict);
    if (clearBtn) clearBtn.addEventListener('click', confirmClear);
  }

  return {
    init:          init,
    addToCart:     addToCart,
    showToast:     showToast,
    closeConflict: closeConflict,
    confirmClear:  confirmClear,
    updateCartUI:  updateCartUI,
  };

})();