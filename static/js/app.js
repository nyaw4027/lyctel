
/* ============================================================
   LYNCTEL — APP INIT
   Loads after DOM ready. Wires global interactions.
   ============================================================ */

document.addEventListener('DOMContentLoaded', function(){

  // ── Flash message auto-dismiss ──────────────────────
  const flash = document.getElementById('flash-wrap');
  if(flash){
    setTimeout(()=>{
      flash.style.transition='opacity .5s';
      flash.style.opacity='0';
      setTimeout(()=>flash.remove(), 500);
    }, 5000);
  }

  // ── Mobile file input fix ───────────────────────────
  // iOS Safari won't open file picker for display:none inputs.
  // Move file inputs inside their labels at runtime.
  document.querySelectorAll('input[type="file"]').forEach(inp=>{
    const cs = window.getComputedStyle(inp);
    if(cs.display==='none'||cs.visibility==='hidden'){
      inp.style.cssText='display:block!important;position:fixed!important;top:-300px!important;left:-300px!important;width:1px!important;height:1px!important;opacity:0!important;pointer-events:none!important;z-index:-1!important;';
    }
  });

  // ── Ripple effect on buttons ────────────────────────
  document.querySelectorAll('.btn, .ripple-container').forEach(btn=>{
    btn.addEventListener('click', function(e){
      const rect = this.getBoundingClientRect();
      const el = document.createElement('span');
      const size = Math.max(rect.width, rect.height);
      el.className='ripple-effect';
      el.style.cssText=`width:${size}px;height:${size}px;left:${e.clientX-rect.left-size/2}px;top:${e.clientY-rect.top-size/2}px;`;
      this.style.position='relative';
      this.style.overflow='hidden';
      this.appendChild(el);
      setTimeout(()=>el.remove(), 600);
    });
  });

  // ── Lazy images ─────────────────────────────────────
  if('IntersectionObserver' in window){
    const obs = new IntersectionObserver((entries)=>{
      entries.forEach(e=>{
        if(e.isIntersecting){
          const img=e.target;
          if(img.dataset.src){ img.src=img.dataset.src; delete img.dataset.src; }
          obs.unobserve(img);
        }
      });
    },{rootMargin:'200px'});
    document.querySelectorAll('img[data-src]').forEach(img=>obs.observe(img));
  }

  // ── Fade-up on scroll ───────────────────────────────
  if('IntersectionObserver' in window){
    const fadeObs = new IntersectionObserver((entries)=>{
      entries.forEach(e=>{
        if(e.isIntersecting){
          e.target.style.opacity='1';
          e.target.style.transform='translateY(0)';
          fadeObs.unobserve(e.target);
        }
      });
    },{threshold:.1});
    document.querySelectorAll('[data-fade]').forEach(el=>{
      el.style.opacity='0';
      el.style.transform='translateY(20px)';
      el.style.transition='opacity .5s ease, transform .5s ease';
      fadeObs.observe(el);
    });
  }

  // ── Quantity selectors ───────────────────────────────
  document.querySelectorAll('.qty-selector').forEach(wrap=>{
    const inp = wrap.querySelector('.qty-input');
    wrap.querySelector('.qty-minus')?.addEventListener('click',()=>{
      const v=parseInt(inp.value)||1;
      if(v>1){ inp.value=v-1; inp.dispatchEvent(new Event('change')); }
    });
    wrap.querySelector('.qty-plus')?.addEventListener('click',()=>{
      const v=parseInt(inp.value)||1;
      inp.value=v+1; inp.dispatchEvent(new Event('change'));
    });
  });

  // ── Dropdown menus ───────────────────────────────────
  document.querySelectorAll('[data-dropdown]').forEach(trigger=>{
    const menu = document.getElementById(trigger.dataset.dropdown);
    if(!menu)return;
    trigger.addEventListener('click',e=>{
      e.stopPropagation();
      menu.classList.toggle('open');
    });
    document.addEventListener('click',()=>menu.classList.remove('open'));
  });

  // ── Modal triggers ───────────────────────────────────
  document.querySelectorAll('[data-modal]').forEach(btn=>{
    const modal = document.getElementById(btn.dataset.modal);
    if(modal) btn.addEventListener('click',()=>modal.classList.add('open'));
  });
  document.querySelectorAll('[data-modal-close]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      btn.closest('.modal-backdrop, .sheet-backdrop, .sheet')?.classList.remove('open');
    });
  });
});
