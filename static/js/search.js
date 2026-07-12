
/* ============================================================
   LYNCTEL — SEARCH
   ============================================================ */

(function(){
  const input = document.getElementById('main-search-input');
  const results = document.getElementById('search-results');
  if(!input || !results) return;

  let controller = null;

  const search = LUtils.debounce(async(q)=>{
    if(q.length < 2){ results.classList.add('hidden'); return; }
    if(controller) controller.abort();
    controller = new AbortController();
    try {
      const data = await fetch(`/api/search/?q=${encodeURIComponent(q)}`,{signal:controller.signal}).then(r=>r.json());
      renderResults(data);
    } catch(e){ if(e.name!=='AbortError') console.error(e); }
  }, 350);

  input.addEventListener('input', e=>search(e.target.value.trim()));
  input.addEventListener('keydown', e=>{
    if(e.key==='Escape'){ results.classList.add('hidden'); input.blur(); }
    if(e.key==='Enter' && input.value.trim()){
      window.location.href = `/search/?q=${encodeURIComponent(input.value.trim())}`;
    }
  });
  document.addEventListener('click', e=>{
    if(!input.contains(e.target) && !results.contains(e.target)) results.classList.add('hidden');
  });

  function renderResults(data) {
    if(!data.results?.length){ results.classList.add('hidden'); return; }
    results.innerHTML = data.results.slice(0,6).map(r=>`
      <a href="${r.url}" class="flex items-center gap-10 px-4 py-3 hover:bg-gray-50 transition-colors">
        ${r.image ? `<img src="${r.image}" class="w-10 h-10 rounded-lg object-cover flex-shrink-0"/>` : '<div class="w-10 h-10 rounded-lg bg-gray-100 flex-shrink-0 flex items-center justify-center text-xl">🛍</div>'}
        <div class="flex-1 min-w-0">
          <p class="text-sm font-semibold text-navy truncate">${LUtils.escape(r.name)}</p>
          <p class="text-xs text-gray-400">${r.category||''}</p>
        </div>
        <p class="text-sm font-bold text-navy flex-shrink-0">GHS ${r.price||''}</p>
      </a>
    `).join('');
    if(data.total > 6) results.innerHTML += `<a href="/search/?q=${encodeURIComponent(input.value)}" class="block text-center text-xs font-semibold text-gold py-3 hover:bg-gray-50">See all ${data.total} results →</a>`;
    results.classList.remove('hidden');
  }
})();
