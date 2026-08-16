/**
 * food.js — Lynctel Food
 *
 * Full cart flow:
 *   1. User taps "+" on any .menu-item-card
 *   2. addToCart() POSTs to cart API (FormData, CSRF safe)
 *   3. On success: #cart-bar animates in, showing count + total
 *   4. Tapping "Checkout →" in the bar goes to /food/checkout/
 *   5. On cart page: stepper and remove work via AJAX
 */

window.Food = (function () {
  'use strict';

  // ── URL resolution ─────────────────────────────────────────────────────────
  function _url(key, fallback) {
    return (window[key]) ? window[key] : fallback;
  }
  function cartAddUrl(id)  { return _url('FOOD_CART_ADD_URL',    '/food/cart/add/')    + id + '/'; }
  function cartUpdUrl(id)  { return _url('FOOD_CART_UPDATE_URL', '/food/cart/update/') + id + '/'; }
  function cartClrUrl()    { return _url('FOOD_CART_CLEAR_URL',  '/food/cart/clear/'); }
  function cartDataUrl()   { return _url('FOOD_CART_DATA_URL',   '/food/cart/data/'); }
  function checkoutUrl()   { return _url('FOOD_CHECKOUT_URL',    '/food/checkout/'); }
  function loginUrl()      { return _url('LOGIN_URL',            '/accounts/login/'); }
  function cartPageUrl()   { return _url('FOOD_CART_URL',        '/food/cart/'); }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function getCsrf() {
    if (typeof CSRF_TOKEN !== 'undefined' && CSRF_TOKEN) return CSRF_TOKEN;
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }
  function isAuth() {
    return typeof IS_AUTHENTICATED !== 'undefined' && !!IS_AUTHENTICATED;
  }
  function post(url, data) {
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    Object.keys(data).forEach(function(k) { fd.append(k, data[k]); });
    return fetch(url, {
      method:  'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body:    fd,
    });
  }

  // ── Toast ──────────────────────────────────────────────────────────────────
  var _t = null, _tt = null;
  function toast(msg, type) {
    if (!_t) {
      _t = document.createElement('div');
      Object.assign(_t.style, {
        position:'fixed', bottom:'90px', left:'50%',
        transform:'translateX(-50%)', zIndex:'9999',
        padding:'11px 22px', borderRadius:'14px',
        fontSize:'13px', fontWeight:'600', color:'white',
        boxShadow:'0 6px 20px rgba(0,0,0,.25)',
        transition:'opacity .25s, transform .25s',
        pointerEvents:'none', whiteSpace:'nowrap',
        maxWidth:'calc(100vw - 32px)', textAlign:'center', opacity:'0',
      });
      document.body.appendChild(_t);
    }
    _t.style.background = {success:'#16a34a',error:'#dc2626',warning:'#d97706',info:'#0F1B2D'}[type]||'#0F1B2D';
    _t.textContent = msg;
    _t.style.opacity = '1';
    _t.style.transform = 'translateX(-50%) translateY(0)';
    clearTimeout(_tt);
    _tt = setTimeout(function () {
      _t.style.opacity = '0';
      _t.style.transform = 'translateX(-50%) translateY(8px)';
    }, 2600);
  }

  // ── Cart bar (HTML element in menu.html) ───────────────────────────────────
  function updateCartUI(count, total) {
    count = parseInt(count, 10) || 0;
    total = parseFloat(total)   || 0;

    // Update the #cart-bar defined in menu.html
    var bar      = document.getElementById('cart-bar');
    var countEl  = document.getElementById('cart-bar-count');
    var totalEl  = document.getElementById('cart-bar-total');
    var spacer   = document.getElementById('cart-bar-spacer');

    if (countEl) countEl.textContent = count;
    if (totalEl) totalEl.textContent = total.toFixed(2);

    if (bar) {
      if (count > 0) {
        bar.classList.remove('d-none');
        bar.style.display = '';
        if (spacer) spacer.classList.remove('d-none');
      } else {
        bar.classList.add('d-none');
        if (spacer) spacer.classList.add('d-none');
      }
    }

    // Nav badge (if present)
    document.querySelectorAll('[data-food-cart-count]').forEach(function (el) {
      el.textContent = count;
      el.style.display = count > 0 ? 'flex' : 'none';
    });
  }

  // ── Conflict modal ─────────────────────────────────────────────────────────
  var _pendingId = null;

  function showConflict(msg) {
    _pendingId = _pendingId; // preserved from caller
    var modal = document.getElementById('conflict-modal');
    if (modal) {
      var el = document.getElementById('conflict-msg');
      if (el) el.textContent = msg || 'You have items from another restaurant.';
      modal.classList.remove('d-none');
      modal.style.display = 'flex';
    } else {
      toast('⚠ Clear your cart first to switch restaurants', 'warning');
    }
  }

  function closeConflict() {
    var modal = document.getElementById('conflict-modal');
    if (modal) { modal.classList.add('d-none'); modal.style.display = ''; }
    _pendingId = null;
  }

  function confirmClear() {
    var id = _pendingId;
    closeConflict();
    post(cartClrUrl(), {})
      .then(function () { if (id) addToCart(id); })
      .catch(function () { toast('Could not clear cart', 'error'); });
  }

  // ── Fetch current cart state ───────────────────────────────────────────────
  function fetchState() {
    if (!isAuth()) return;
    fetch(cartDataUrl(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) updateCartUI(d.count || 0, d.total || 0); })
      .catch(function () {});
  }

  // ── Add to cart ────────────────────────────────────────────────────────────
  function addToCart(itemId, qty) {
    qty = qty || 1;

    if (!isAuth()) {
      window.location.href = loginUrl() + '?next=' + encodeURIComponent(window.location.pathname);
      return;
    }

    if (!getCsrf()) {
      toast('Session error — please refresh', 'error');
      return;
    }

    // Dim card while request in flight
    var cards = document.querySelectorAll('[data-food-item="' + itemId + '"]');
    cards.forEach(function (c) { c.style.opacity = '0.5'; c.style.pointerEvents = 'none'; });

    post(cartAddUrl(itemId), { quantity: qty })
      .then(function (res) {
        // 302 redirect = session expired → login
        if (res.redirected || res.url.indexOf('/login') !== -1 || res.url.indexOf('/accounts/') !== -1) {
          window.location.href = loginUrl() + '?next=' + encodeURIComponent(window.location.pathname);
          return null;
        }
        if (res.status === 403) { toast('Security error — refresh the page', 'error'); return null; }
        if (!res.ok) {
          console.error('[Food] cart_add HTTP ' + res.status);
          return res.json().catch(function () { return null; });
        }
        return res.json();
      })
      .then(function (d) {
        if (!d) return;
        if (d.conflict) {
          _pendingId = itemId;
          showConflict(d.message);
          return;
        }
        if (d.success !== false) {
          var count = d.cart_count || d.count || 0;
          var total = d.cart_total || d.total || 0;
          updateCartUI(count, total);
          toast('✓ Added to cart', 'success');

          // Flash the + button for this item
          var btn = document.querySelector('[data-food-item="' + itemId + '"] .menu-add-btn');
          if (btn) {
            var orig = btn.textContent;
            btn.textContent = '✓';
            btn.style.background = '#16a34a';
            setTimeout(function () {
              btn.textContent = orig;
              btn.style.background = '';
            }, 900);
          }

          // Bounce the cart bar badge
          var countEl = document.getElementById('cart-bar-count');
          if (countEl) {
            countEl.style.transform = 'scale(1.5)';
            setTimeout(function () { countEl.style.transform = ''; }, 200);
          }
        } else {
          toast(d.error || 'Could not add item', 'warning');
          console.warn('[Food] cart_add error response:', d);
        }
      })
      .catch(function (e) {
        console.error('[Food] addToCart error:', e);
        toast('Connection error — try again', 'error');
      })
      .finally(function () {
        cards.forEach(function (c) { c.style.opacity = ''; c.style.pointerEvents = ''; });
      });
  }

  // ── Cart page: stepper + remove ────────────────────────────────────────────
  function initCartPage() {
    if (!document.querySelector('[data-food-cart-page],[data-food-cart-list]')) return;

    document.querySelectorAll('[data-food-update-form]').forEach(function (form) {
      var input  = form.querySelector('input[type="number"]');
      var pk     = form.dataset.itemPk;
      if (!input || !pk) return;

      var minus = form.querySelector('[data-minus]');
      var plus  = form.querySelector('[data-plus]');

      if (minus) minus.addEventListener('click', function () {
        var v = Math.max(0, (parseInt(input.value, 10) || 1) - 1);
        if (v === 0) removeItem(pk, form.closest('[data-food-item-row]'));
        else { input.value = v; updateItem(pk, v); }
      });

      if (plus) plus.addEventListener('click', function () {
        var v = (parseInt(input.value, 10) || 0) + 1;
        input.value = v;
        updateItem(pk, v);
      });

      input.addEventListener('change', function () {
        var v = parseInt(input.value, 10) || 0;
        if (v <= 0) removeItem(pk, form.closest('[data-food-item-row]'));
        else updateItem(pk, v);
      });
    });

    document.querySelectorAll('[data-food-remove-btn]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        removeItem(btn.dataset.foodRemoveBtn, btn.closest('[data-food-item-row]'));
      });
    });
  }

  function updateItem(pk, qty) {
    post(cartUpdUrl(pk), { quantity: qty })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
        if (d.new_total != null) {
          var el = document.querySelector('[data-item-total="' + pk + '"]');
          if (el) el.textContent = 'GHS ' + parseFloat(d.new_total).toFixed(2);
        }
        refreshSummary();
      })
      .catch(function (e) { console.error('[Food] updateItem:', e); toast('Update failed', 'error'); });
  }

  function removeItem(pk, row) {
    if (row) row.style.opacity = '0.4';
    post(cartUpdUrl(pk), { quantity: 0 })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (row) row.remove();
        updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
        refreshSummary();
        if (!document.querySelectorAll('[data-food-item-row]').length) {
          var empty = document.querySelector('[data-food-cart-empty]');
          var list  = document.querySelector('[data-food-cart-list]');
          if (empty) { empty.style.display = 'block'; }
          if (list)  { list.style.display  = 'none';  }
          var btn = document.querySelector('[data-food-checkout-btn]');
          if (btn) btn.style.display = 'none';
        }
      })
      .catch(function (e) {
        if (row) row.style.opacity = '';
        console.error('[Food] removeItem:', e);
        toast('Remove failed', 'error');
      });
  }

  function refreshSummary() {
    fetch(cartDataUrl(), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        updateCartUI(d.count || d.cart_count || 0, d.total || d.cart_total || 0);
        var sub = document.querySelector('[data-cart-subtotal]');
        var del = document.querySelector('[data-cart-delivery]');
        var tot = document.querySelector('[data-cart-total]');
        var s   = parseFloat(d.subtotal || d.total || 0);
        var df  = parseFloat(d.delivery || 0);
        if (sub) sub.textContent = 'GHS ' + s.toFixed(2);
        if (del) del.textContent = 'GHS ' + df.toFixed(2);
        if (tot) tot.textContent = 'GHS ' + (s + df).toFixed(2);
      })
      .catch(function () {});
  }

  // ── Scroll spy for category nav ────────────────────────────────────────────
  function initScrollSpy() {
    var sections = document.querySelectorAll('section[id^="cat-"]');
    var btns     = document.querySelectorAll('.food-cat-btn');
    if (!sections.length || !btns.length) return;
    if (!('IntersectionObserver' in window)) return;
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        btns.forEach(function (b) {
          b.classList.toggle('active', b.getAttribute('href') === '#' + e.target.id);
        });
      });
    }, { rootMargin: '-30% 0px -60% 0px', threshold: 0 });
    sections.forEach(function (s) { obs.observe(s); });
  }

  // ── Fade-in on scroll ──────────────────────────────────────────────────────
  function initFadeIn() {
    if (!('IntersectionObserver' in window)) return;
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.style.opacity    = '1';
          e.target.style.transform  = 'translateY(0)';
          obs.unobserve(e.target);
        }
      });
    }, { threshold: 0.08 });
    document.querySelectorAll('.menu-item-card').forEach(function (c, i) {
      c.style.cssText += 'opacity:0;transform:translateY(10px);'
        + 'transition:opacity .3s ease ' + (i * 0.035) + 's,'
        + 'transform .3s ease ' + (i * 0.035) + 's';
      obs.observe(c);
    });
  }

  // ── Main init ──────────────────────────────────────────────────────────────
  function init() {
    fetchState();   // restore cart bar count from server on page load
    initCartPage();
    initScrollSpy();
    initFadeIn();

    // Conflict modal close/clear buttons
    var keep  = document.querySelector('#conflict-modal .btn-keep');
    var clear = document.querySelector('#conflict-modal .btn-clear');
    if (keep)  keep.addEventListener('click',  closeConflict);
    if (clear) clear.addEventListener('click', confirmClear);

    // Smooth scroll for category nav
    document.querySelectorAll('.food-cat-btn').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        var href = btn.getAttribute('href');
        if (!href || href[0] !== '#') return;
        e.preventDefault();
        var target = document.getElementById(href.slice(1));
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  return {
    init:          init,
    addToCart:     addToCart,
    toast:         toast,
    showToast:     toast,
    closeConflict: closeConflict,
    confirmClear:  confirmClear,
    updateCartUI:  updateCartUI,
  };
})();