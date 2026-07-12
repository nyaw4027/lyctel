
/* ============================================================
   LYNCTEL — UPLOADS
   Universal file upload handler for all forms.
   ============================================================ */

window.LUpload = {
  /* Setup a dropzone — works on mobile (label pattern) and desktop (drag/drop) */
  setup(zoneId, fileId, previewId, opts={}) {
    const zone   = document.getElementById(zoneId);
    const input  = document.getElementById(fileId);
    const preview= document.getElementById(previewId);
    if(!zone||!input) return;

    const {
      maxSizeMB  = 5,
      accept     = ['image/'],
      onSuccess  = ()=>{},
      onError    = (msg)=>LUtils.toast(msg,'error'),
      errElId    = null,
    } = opts;

    function validate(file) {
      if(!file) return 'No file selected.';
      if(!accept.some(a=>file.type.startsWith(a))) return `Invalid file type. Accepted: ${accept.join(', ')}`;
      if(file.size > maxSizeMB*1024*1024) return `File too large — max ${maxSizeMB}MB.`;
      return null;
    }

    function process(file) {
      const err = validate(file);
      if(err){ onError(err); if(errElId){ const e=document.getElementById(errElId); if(e){e.textContent=err;e.classList.remove('hidden');} } return; }
      const reader = new FileReader();
      reader.onload = ev=>{
        if(preview){
          preview.src = ev.target.result;
          preview.classList.remove('hidden');
          preview.style.display='block';
        }
        // Dim placeholder text
        zone.querySelectorAll('[data-upload-idle]').forEach(el=>el.style.opacity='.35');
        // Show remove button
        zone.querySelector('[data-upload-remove]')?.classList.remove('hidden');
        onSuccess(ev.target.result, file);
      };
      reader.readAsDataURL(file);
    }

    // File input change
    input.addEventListener('change', ()=>{ if(input.files[0]) process(input.files[0]); });

    // Drag and drop (desktop)
    ['dragover','dragenter'].forEach(ev=>zone.addEventListener(ev,e=>{e.preventDefault();zone.classList.add('over');}));
    ['dragleave','drop'].forEach(ev=>zone.addEventListener(ev,e=>{e.preventDefault();zone.classList.remove('over');}));
    zone.addEventListener('drop', e=>{
      const file=e.dataTransfer?.files[0]; if(!file)return;
      try{ const dt=new DataTransfer(); dt.items.add(file); input.files=dt.files; }catch{}
      process(file);
    });
  },

  remove(zoneId, fileId, previewId) {
    const input  = document.getElementById(fileId);
    const preview= document.getElementById(previewId);
    const zone   = document.getElementById(zoneId);
    if(input)   input.value='';
    if(preview){ preview.src=''; preview.classList.add('hidden'); preview.style.display='none'; }
    if(zone){
      zone.querySelectorAll('[data-upload-idle]').forEach(el=>el.style.opacity='1');
      zone.querySelector('[data-upload-remove]')?.classList.add('hidden');
    }
  },
};
