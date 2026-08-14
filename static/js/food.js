/**
 * food.js — Lynctel Food: unified cart + menu client JS
 *
 * FIXED: The previous file had TWO separate `const Food = ...` blocks
 * concatenated together. The second block began with 'use strict'; which
 * caused a SyntaxError ("Identifier 'Food' has already been declared")
 * that silently killed ALL cart functionality on every food page.
 *
 * This single file merges both versions:
 *   - CSRF reading from base.html's global CSRF_TOKEN (reliable)
 *   - FormData POST body (works with Django's default form parser)
 *   - Toast notifications
 *   - Conflict modal (different restaurant in cart)
 *   - #cart-bar badge updates
 *   - Cart page: stepper buttons, AJAX remove/update
 *   - Scroll spy for category nav
 *   - Fade-in animation for menu cards
 */

window.Food = (function () {

  // ── CSRF & auth ──────────────────────────────────────────
  // base.html exposes CSRF_TOKEN and IS_AUTHENTICATED as globals.
  function getCsrf() {
    if (typeof CSRF_TOKEN !== 'undefined' && CSRF_TOKEN) return CSRF_TOKEN;
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function isAuthenticated() {
    return typeof IS_AUTHENTICATED !== 'undefined' && IS_AUTHENTICATED;
  }

  function getLoginUrl() {
    return typeof LOGIN_URL !== 'undefined' ? LOGIN_URL : '/accounts/login/';
  }

  // ── Toast ─────────────────────────────────────────────────
  var toastEl = null;
  var toastTimer = null;

  function showToast(message, type) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.id = 'food-toast';
      Object.assign(toastEl.style, {
        position: 'fixed',
        bottom: '80px',
        left: '50%',
        transform: 'translateX(-50%) translateY(0)',
        zIndex: '9999',
        padding: '12px 20px',
        borderRadius: '14px',
        fontSize: '13px',
        fontWeight: '600',
        color: 'white',
        boxShadow: '0 8px 24px rgba(0,0,0,.25)',
        transition: 'opacity .3s,transform .3s',
        pointerEvents: 'none',
        whiteSpace: 'nowrap',
        maxWidth: 'calc(100vw - 32px)',
        textAlign: 'center',
        opacity: '0',
      });
      document.body.appendChild(toastEl);
    }
    var colors = { success:'#16a34a', error:'#dc2626', warning:'#d97706', info:'#0F1B2D' };
    toastEl.style.background = colors[type] || colors.info;
    toastEl.textContent = message;
    toastEl.style.opacity = '1';
    toastEl.style.transform = 'translateX(-50%) translateY(0)';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.style.opacity = '0';
      toastEl.style.transform = 'translateX(-50%) translateY(8px)';
    }, 2800);
  }

  // ── Cart bar / badge updates ──────────────────────────────
  // Supports both the #cart-bar element (from the original version)
  // and [data-food-cart-count] attributes (from the fixed version).
  function updateCartUI(count, total) {
    count = count || 0;
    total = parseFloat(total) || 0;

    // #cart-bar (floating bar shown on menu/home pages)
    var bar = document.getElementById('cart-bar');
    var countEl = document.getElementById('cart-bar-count');
    var totalEl = document.getElementById('cart-bar-total');
    if (countEl) countEl.textContent = count;
    if (totalEl) totalEl.textContent = 'GHS ' + total.toFixed(2);
    if (bar) bar.classList.toggle('d-none', count <= 0);

    // [data-food-cart-count] badges
    document.querySelectorAll('[data-food-cart-count]').forEach(function (el) {
      el.textContent = count;
      el.style.display = count > 0 ? 'flex' : 'none';
    });
  }

  // ── Conflict modal ────────────────────────────────────────
  // Shown when the user taps an item from a different restaurant
  // while their cart already has items.
  var pendingItemId = null;

  function showConflictModal(message) {
    var modal = document.getElementById('conflict-modal');
    if (!modal) {
      // Fallback: no modal in template — use toast
      showToast('⚠ Clear your cart first to order from this restaurant', 'warning');
      return;
    }
    var msgEl = document.getElementById('conflict-msg');
    if (msgEl) msgEl.textContent = message || 'You have items from another restaurant in your cart.';
    modal.classList.remove('d-none');
  }

  function closeConflict() {
    var modal = document.getElementById('conflict-modal');
    if (modal) modal.classList.add('d-none');
    pendingItemId = null;
  }

  function confirmClear() {
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fetch('/food/cart/clear/', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
    }).then(function () {
      var id = pendingItemId;
      closeConflict();
      if (id) addToCart(id);
    }).catch(function (err) { console.warn('[Food] confirmClear error', err); });
  }

  // ── Fetch cart state ──────────────────────────────────────
  function fetchCartState() {
    if (!isAuthenticated()) return;
    fetch('/food/cart/data/', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    }).then(function (r) {
      return r.json();
    }).then(function (d) {
      if (d) updateCartUI(d.count || d.cart_count || 0, d.total || d.cart_total || 0);
    }).catch(function () {});
  }

  // ── Add to cart ───────────────────────────────────────────
  function addToCart(itemId) {
    if (!isAuthenticated()) {
      window.location.href = getLoginUrl() + '?next=' + encodeURIComponent(window.location.pathname);
      return;
    }

    var csrf = getCsrf();
    if (!csrf) { showToast('Session error — please refresh', 'error'); return; }

    // Dim all matching cards for this item while the request is in flight
    var cards = document.querySelectorAll('[data-food-item="' + itemId + '"]');
    cards.forEach(function (c) { c.style.opacity = '0.6'; c.style.pointerEvents = 'none'; });

    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', csrf);
    fd.append('quantity', 1);

    fetch('/food/cart/add/' + itemId + '/', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
    })
      .then(function (res) {
        if (res.status === 403) throw new Error('auth');
        if (!res.ok) throw new Error('server');
        return res.json();
      })
      .then(function (d) {
        if (d.conflict) {
          pendingItemId = itemId;
          showConflictModal(d.message);
          return;
        }
        if (d.success || d.cart_count !== undefined) {
          updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
          showToast('✓ Added to cart', 'success');

          // Button flash feedback
          var btn = document.getElementById('add-btn-' + itemId);
          if (btn) {
            var orig = btn.textContent;
            btn.textContent = '✓';
            setTimeout(function () { btn.textContent = orig; }, 900);
          }
        } else if (d.error) {
          showToast(d.error, 'warning');
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
        cards.forEach(function (c) { c.style.opacity = ''; c.style.pointerEvents = ''; });
      });
  }

  // ── Cart page: stepper + AJAX remove ─────────────────────
  function initCartPage() {
    // Only activate on pages that mark themselves as the cart page
    var cartList = document.querySelector('[data-food-cart-page], [data-food-cart-list]');
    if (!cartList) return;

    // Stepper forms
    document.querySelectorAll('[data-food-update-form]').forEach(function (form) {
      var input  = form.querySelector('input[type="number"]');
      var itemPk = form.dataset.itemPk;
      if (!input || !itemPk) return;

      var minusBtn = form.querySelector('[data-minus]');
      var plusBtn  = form.querySelector('[data-plus]');

      if (minusBtn) {
        minusBtn.addEventListener('click', function () {
          var v = parseInt(input.value, 10) || 1;
          if (v <= 1) {
            cartRemoveItem(itemPk, form.closest('[data-food-item-row]'));
          } else {
            input.value = v - 1;
            cartUpdateItem(itemPk, v - 1);
          }
        });
      }
      if (plusBtn) {
        plusBtn.addEventListener('click', function () {
          var v = parseInt(input.value, 10) || 1;
          input.value = v + 1;
          cartUpdateItem(itemPk, v + 1);
        });
      }
      input.addEventListener('change', function () {
        var v = parseInt(input.value, 10) || 0;
        if (v <= 0) {
          cartRemoveItem(itemPk, form.closest('[data-food-item-row]'));
        } else {
          cartUpdateItem(itemPk, v);
        }
      });
    });

    // Remove buttons
    document.querySelectorAll('[data-food-remove-btn]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var row    = btn.closest('[data-food-item-row]');
        var itemPk = btn.dataset.foodRemoveBtn;
        cartRemoveItem(itemPk, row);
      });
    });
  }

  function cartUpdateItem(itemPk, quantity) {
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fd.append('quantity', quantity);
    fetch('/food/cart/update/' + itemPk + '/', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
        if (d.new_total !== undefined) {
          var el = document.querySelector('[data-item-total="' + itemPk + '"]');
          if (el) el.textContent = 'GHS ' + parseFloat(d.new_total).toFixed(2);
        }
        refreshCartSummary();
      })
      .catch(function () { showToast('Update failed — try again', 'error'); });
  }

  function cartRemoveItem(itemPk, row) {
    if (row) { row.style.opacity = '0.4'; row.style.transition = 'opacity .25s'; }
    var fd = new FormData();
    fd.append('csrfmiddlewaretoken', getCsrf());
    fd.append('quantity', 0);
    fetch('/food/cart/update/' + itemPk + '/', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: fd,
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (row) row.remove();
        updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
        refreshCartSummary();
        // Show empty state if nothing left
        var remaining = document.querySelectorAll('[data-food-item-row]');
        if (!remaining.length) {
          var emptyEl = document.querySelector('[data-food-cart-empty]');
          var listEl  = document.querySelector('[data-food-cart-list]');
          if (emptyEl) { emptyEl.style.display = 'block'; }
          if (listEl)  { listEl.style.display  = 'none';  }
          var checkoutBtn = document.querySelector('[data-food-checkout-btn]');
          if (checkoutBtn) checkoutBtn.style.display = 'none';
        }
      })
      .catch(function () {
        if (row) row.style.opacity = '';
        showToast('Remove failed — try again', 'error');
      });
  }

  function refreshCartSummary() {
    fetch('/food/cart/data/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        updateCartUI(d.cart_count || d.count || 0, d.cart_total || d.total || 0);
        var sub = document.querySelector('[data-cart-subtotal]');
        var del = document.querySelector('[data-cart-delivery]');
        var tot = document.querySelector('[data-cart-total]');
        if (sub) sub.textContent = 'GHS ' + parseFloat(d.subtotal || 0).toFixed(2);
        if (del) del.textContent = 'GHS ' + parseFloat(d.delivery || 0).toFixed(2);
        if (tot) tot.textContent = 'GHS ' + parseFloat(d.total    || 0).toFixed(2);
      })
      .catch(function () {});
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
          var id = entry.target.id;
          catBtns.forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('href') === '#' + id);
          });
        });
      }, { rootMargin: '-30% 0px -60% 0px', threshold: 0 });
      sections.forEach(function (s) { obs.observe(s); });
    } else {
      // Fallback: scroll event
      function onScroll() {
        var current = '';
        sections.forEach(function (s) {
          if (window.scrollY + 120 >= s.offsetTop) current = s.id;
        });
        catBtns.forEach(function (btn) {
          btn.classList.toggle('active', btn.getAttribute('href') === '#' + current);
        });
      }
      window.addEventListener('scroll', onScroll, { passive: true });
      onScroll();
    }
  }

  // ── Fade-in on scroll ─────────────────────────────────────
  function initFadeIn() {
    if (!('IntersectionObserver' in window)) return;
    var cards = document.querySelectorAll('.menu-item-card');
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.style.opacity = '1';
          entry.target.style.transform = 'translateY(0)';
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1 });
    cards.forEach(function (card, i) {
      card.style.opacity = '0';
      card.style.transform = 'translateY(12px)';
      card.style.transition = 'opacity .35s ease ' + (i * 0.04) + 's, transform .35s ease ' + (i * 0.04) + 's';
      obs.observe(card);
    });
  }

  // ── Scroll position preservation (home page) ──────────────
  function preserveScroll() {
    try {
      var key = 'food_home_scroll_v2';
      var stored = sessionStorage.getItem(key);
      if (stored) window.scrollTo(0, parseInt(stored, 10) || 0);
      window.addEventListener('beforeunload', function () {
        sessionStorage.setItem(key, window.scrollY || 0);
      });
    } catch (e) {}
  }

  // ── Init ──────────────────────────────────────────────────
  function init() {
    fetchCartState();
    initCartPage();
    initScrollSpy();
    initFadeIn();
    preserveScroll();

    // Wire up conflict modal buttons if they exist in the template
    var keepBtn  = document.querySelector('#conflict-modal .btn-keep');
    var clearBtn = document.querySelector('#conflict-modal .btn-clear');
    if (keepBtn)  keepBtn.addEventListener('click',  closeConflict);
    if (clearBtn) clearBtn.addEventListener('click', confirmClear);
  }

  // Cart pop animation CSS (injected once)
  (function () {
    var s = document.createElement('style');
    s.textContent = '@keyframes foodCartPop{0%,100%{transform:scale(1)}50%{transform:scale(1.4)}}.food-cart-pop{animation:foodCartPop .4s ease}';
    document.head.appendChild(s);
  })();

  return {
    init:          init,
    addToCart:     addToCart,
    showToast:     showToast,
    closeConflict: closeConflict,
    confirmClear:  confirmClear,
  };

})();