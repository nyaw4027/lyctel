
/* ============================================================
   LYNCTEL — NAVBAR
   ============================================================ */

(function(){
  // Scroll shadow
  const nav = document.getElementById('navbar');
  if(nav){
    window.addEventListener('scroll', ()=>{
      nav.classList.toggle('nav-scrolled', window.scrollY > 10);
    }, {passive:true});
  }

  // Mobile search expand
  const searchToggle = document.getElementById('nav-search-toggle');
  const searchBar    = document.getElementById('nav-search-bar');
  if(searchToggle && searchBar){
    searchToggle.addEventListener('click', ()=>{
      searchBar.classList.toggle('hidden');
      if(!searchBar.classList.contains('hidden')) searchBar.querySelector('input')?.focus();
    });
  }

  // Highlight active nav link
  const current = window.location.pathname;
  document.querySelectorAll('.navbar-link').forEach(a=>{
    if(a.getAttribute('href') === current) a.classList.add('active');
  });
})();
