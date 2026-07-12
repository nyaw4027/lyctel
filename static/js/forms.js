
/* ============================================================
   LYNCTEL — FORMS
   Validation, character counters, auto-resize.
   ============================================================ */

(function(){
  // Auto-resize textareas
  document.querySelectorAll('textarea[data-autoresize]').forEach(ta=>{
    function resize(){ ta.style.height='auto'; ta.style.height=ta.scrollHeight+'px'; }
    ta.addEventListener('input', resize);
    resize();
  });

  // Character counters
  document.querySelectorAll('[data-maxlen]').forEach(inp=>{
    const max     = parseInt(inp.dataset.maxlen);
    const countEl = document.getElementById(inp.dataset.counter);
    if(!countEl) return;
    inp.addEventListener('input',()=>{
      const len=inp.value.length;
      countEl.textContent=`${len}/${max}`;
      countEl.style.color = len > max*0.9 ? 'var(--error)' : 'var(--gray-400)';
    });
    inp.dispatchEvent(new Event('input'));
  });

  // Phone format (Ghana 10-digit)
  document.querySelectorAll('input[data-phone]').forEach(inp=>{
    inp.addEventListener('blur',()=>{
      const v=inp.value.replace(/\D/g,'');
      if(v.length===10) inp.classList.add('f-ok');
      else if(v.length>0) inp.classList.add('f-bad');
    });
  });

  // Password strength
  const pwdInput = document.getElementById('new-password');
  const pwdBar   = document.getElementById('pwd-strength-bar');
  const pwdLabel = document.getElementById('pwd-strength-label');
  if(pwdInput && pwdBar){
    pwdInput.addEventListener('input',()=>{
      const v=pwdInput.value;
      const checks=[v.length>=8,/[A-Z]/.test(v),/[0-9]/.test(v),/[^A-Za-z0-9]/.test(v)];
      const score=checks.filter(Boolean).length;
      const colors=['','var(--error)','var(--warning)','var(--info)','var(--success)'];
      const labels=['','Weak','Fair','Good','Strong'];
      pwdBar.style.width=(score/4*100)+'%';
      pwdBar.style.background=colors[score];
      if(pwdLabel){ pwdLabel.textContent=v?labels[score]:''; pwdLabel.style.color=colors[score]; }
    });
  }
})();
