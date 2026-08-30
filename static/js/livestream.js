const STREAM_ID  = window.STREAM_ID || '';          // set by broadcast.html before this file loads
const WS_SCHEME  = location.protocol === 'https:' ? 'wss' : 'ws';
const WS_URL     = window.WS_URL || `${WS_SCHEME}://${location.host}/ws/stream/${STREAM_ID}/`;
const END_URL    = window.END_URL    || `/livestream/${STREAM_ID}/end/`;
const PIN_URL    = window.PIN_URL    || `/livestream/${STREAM_ID}/pin-product/`;
const UPLOAD_URL = window.UPLOAD_URL || `/livestream/${STREAM_ID}/upload-recording/`;
// CSRF_TOKEN declared in base.html

const pinnedSet = new Set(window.PINNED_IDS || []);  // PINNED_IDS set by broadcast.html

let ws, localStream, facingMode = 'user';
let peerConnections = {};
let camOn = true, micOn = true;
let startTime = null, timerInterval = null;
let chatCount = 0, totalGifts = 0;
let currentPinnedId = null;

// ── RECORDING (client-side, until there's an SFU to record server-side) ──
// There's no media server between broadcaster and viewers right now — it's
// a straight peer-to-peer mesh — so nothing server-side ever "sees" one
// unified stream to record. The only stream that reliably exists start to
// finish is the broadcaster's own local camera feed, so that's what gets
// recorded and uploaded here. This gives VOD playback; it does NOT fix the
// mesh's scaling problem (see the bitrate-scaling note in handleViewerOffer).
let mediaRecorder = null;
let recordedChunks = [];

function startRecording() {
  if (!localStream || typeof MediaRecorder === 'undefined') return;
  recordedChunks = [];
  const mimeType = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm']
    .find(t => MediaRecorder.isTypeSupported(t)) || '';
  try {
    mediaRecorder = new MediaRecorder(localStream, mimeType ? { mimeType } : undefined);
  } catch (e) {
    console.warn('[recording] MediaRecorder unavailable:', e);
    return;
  }
  mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) recordedChunks.push(e.data); };
  mediaRecorder.start(1000); // 1s chunks so a crash doesn't lose the whole recording
  document.getElementById('rec-badge').style.display = 'inline-flex';
}

function stopRecordingAndUpload() {
  return new Promise((resolve) => {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') { resolve(null); return; }

    // Safety timeout — never block endStream for more than 25s
    const bail = setTimeout(() => {
      console.warn('[recording] upload timed out — proceeding without replay');
      resolve(null);
    }, 25000);

    mediaRecorder.onstop = async () => {
      const badge = document.getElementById('rec-badge');
      if (badge) badge.style.display = 'none';

      if (recordedChunks.length === 0) { clearTimeout(bail); resolve(null); return; }

      const blob = new Blob(recordedChunks, { type: 'video/webm' });
      try {
        const fd = new FormData();
        fd.append('recording', blob, STREAM_ID + '.webm');
        const controller = new AbortController();
        const uploadKill  = setTimeout(() => controller.abort(), 20000);
        const res  = await fetch(UPLOAD_URL, {
          method:  'POST',
          headers: { 'X-CSRFToken': CSRF_TOKEN },
          body:    fd,
          signal:  controller.signal,
        });
        clearTimeout(uploadKill);
        const data = await res.json();
        clearTimeout(bail);
        resolve(data.success ? data.recording_url : null);
      } catch (e) {
        console.error('[recording] upload failed:', e);
        clearTimeout(bail);
        resolve(null);
      }
    };
    mediaRecorder.stop();
  });
}

// ── PEAK VIEWERS ──────────────────────────────────────────
// So the recap and the streamer both see the real high-water mark, not
// just whatever the live count happened to be at the moment someone looked.
let peakViewers = 0;

const iceConfig = {
  iceServers:[
    {urls:'stun:stun.l.google.com:19302'},
    {urls:'stun:stun1.l.google.com:19302'},
  ]
};

// ── CAMERA ────────────────────────────────────────────────
async function startCamera() {
  console.log('[camera] startCamera() called — STREAM_ID:', STREAM_ID);
  const placeholder = document.getElementById('cam-placeholder');
  const startBtn    = placeholder ? placeholder.querySelector('button') : null;

  // Show loading state
  if (startBtn) {
    startBtn.disabled    = true;
    startBtn.textContent = '⏳ Requesting camera…';
  }

  try {
    // Check getUserMedia is available (HTTPS required)
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error('Camera access requires HTTPS. Make sure you are on a secure connection.');
    }

    localStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode },
      audio: { echoCancellation: true, noiseSuppression: true },
    });

    const video = document.getElementById('local-video');
    if (video) video.srcObject = localStream;

    if (placeholder) placeholder.style.display = 'none';

    const badge = document.getElementById('live-badge');
    if (badge) badge.style.display = 'inline-flex';

    startTime = Date.now();
    startTimer();
    connectWS();
    startRecording();

  } catch(err) {
    // Restore button
    if (startBtn) {
      startBtn.disabled    = false;
      startBtn.textContent = '🔴 Start Camera';
    }

    // Show friendly in-page error (no alert() — blocked on mobile Safari)
    let msg = 'Could not access camera.';
    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      msg = '📵 Camera permission denied. Please allow camera access in your browser settings and try again.';
    } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
      msg = '📷 No camera found on this device.';
    } else if (err.name === 'NotReadableError') {
      msg = '🔒 Camera is already in use by another app. Close other apps and try again.';
    } else if (err.message.includes('HTTPS')) {
      msg = err.message;
    } else {
      msg = '⚠️ Camera error: ' + err.message;
    }

    if (placeholder) {
      const errDiv = document.createElement('p');
      errDiv.style.cssText = 'color:#fca5a5;font-size:14px;margin:12px 0 0;max-width:300px;text-align:center;';
      errDiv.textContent   = msg;
      // Remove any previous error
      const prev = placeholder.querySelector('.cam-error');
      if (prev) prev.remove();
      errDiv.className = 'cam-error';
      placeholder.appendChild(errDiv);
    }

    console.error('[camera]', err);
  }
}

function toggleCamera() {
  if(!localStream) return;
  camOn = !camOn;
  localStream.getVideoTracks().forEach(t=>t.enabled=camOn);
  document.getElementById('cam-icon').textContent = camOn ? '📷' : '📷❌';
  document.getElementById('cam-label').textContent = camOn ? 'Camera' : 'Camera Off';
}

function toggleMic() {
  if(!localStream) return;
  micOn = !micOn;
  localStream.getAudioTracks().forEach(t=>t.enabled=micOn);
  document.getElementById('mic-icon').textContent = micOn ? '🎤' : '🔇';
  document.getElementById('mic-label').textContent = micOn ? 'Mic' : 'Muted';
}

async function switchCamera() {
  facingMode = facingMode === 'user' ? 'environment' : 'user';
  if(!localStream) return;
  try {
    const newStream = await navigator.mediaDevices.getUserMedia({video:{facingMode},audio:true});
    const newTrack  = newStream.getVideoTracks()[0];
    const oldTrack  = localStream.getVideoTracks()[0];
    if(oldTrack){ oldTrack.stop(); localStream.removeTrack(oldTrack); }
    localStream.addTrack(newTrack);
    document.getElementById('local-video').srcObject = localStream;
    Object.values(peerConnections).forEach(pc=>{
      const s=pc.getSenders().find(s=>s.track?.kind==='video');
      if(s) s.replaceTrack(newTrack);
    });
  } catch(e){console.error('Switch camera:',e);}
}

// ── WEBSOCKET ─────────────────────────────────────────────
function connectWS() {
  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    // Tell the server this is the vendor/broadcaster connection
    try {
      ws.send(JSON.stringify({ type: 'vendor_init', stream_id: STREAM_ID }));
    } catch(e) { console.warn('[ws] vendor_init failed:', e); }
  };
  ws.onmessage = async({data}) => {
    let msg; try{msg=JSON.parse(data);}catch{return;}
    switch(msg.type){
      case 'offer':
        await handleViewerOffer(msg.sdp, msg.sender);
        break;
      case 'answer':
        if(peerConnections[msg.sender])
          await peerConnections[msg.sender].setRemoteDescription(
            new RTCSessionDescription({type:'answer',sdp:msg.sdp})
          ).catch(()=>{});
        break;
      case 'ice':
        if(msg.sender && peerConnections[msg.sender])
          await peerConnections[msg.sender].addIceCandidate(
            new RTCIceCandidate(msg.candidate)
          ).catch(()=>{});
        break;
      case 'viewer_count':
        document.getElementById('viewer-count').textContent = msg.count;
        if (msg.count > peakViewers) peakViewers = msg.count;
        break;
      case 'chat':
        appendChat(msg);
        break;
      case 'gift':
        handleGift(msg);
        break;
      case 'poll_vote':
        recordPollVote(msg.option);
        break;
      case 'pinned_products':
        if(msg.products?.length){
          const h=msg.products.find(p=>p.is_highlighted);
          if(h) showPinnedBar(h);
        }
        break;
      case 'product_pinned':
        if(msg.product) showPinnedBar(msg.product);
        break;
    }
  };
  ws.onclose = () => setTimeout(()=>{if(localStream)connectWS();},3000);
}

// ── WEBRTC ────────────────────────────────────────────────
// Rough bitrate scaling for the mesh: as more viewers connect, the
// broadcaster's single upload pipe has to carry all of them at once, so
// each additional connection gets capped a little lower. This buys some
// headroom before the connection saturates — it does not remove the O(N)
// upload cost itself. Past a handful of concurrent viewers this stops
// being enough and you need an SFU (see note at the top of this file).
function targetBitrateForViewerCount(count) {
  if (count <= 3)  return 1_500_000; // ~1.5 Mbps — near-full quality
  if (count <= 8)  return 900_000;
  if (count <= 15) return 500_000;
  return 300_000; // heavily degraded — this is the mesh telling you it needs an SFU
}

async function applyBitrateCap(pc) {
  const sender = pc.getSenders().find(s => s.track && s.track.kind === 'video');
  if (!sender) return;
  const count = Object.keys(peerConnections).length;
  const params = sender.getParameters();
  if (!params.encodings) params.encodings = [{}];
  params.encodings[0].maxBitrate = targetBitrateForViewerCount(count);
  try { await sender.setParameters(params); } catch (e) { /* not fatal */ }
}

async function handleViewerOffer(sdp, viewerChannel) {
  if(!localStream || !viewerChannel) return;
  if(peerConnections[viewerChannel]) peerConnections[viewerChannel].close();

  const pc = new RTCPeerConnection(iceConfig);
  peerConnections[viewerChannel] = pc;

  localStream.getTracks().forEach(t=>pc.addTrack(t,localStream));

  pc.onicecandidate = ({candidate})=>{
    if(candidate && ws?.readyState===1)
      ws.send(JSON.stringify({type:'ice',candidate,peer_id:viewerChannel}));
  };
  pc.onconnectionstatechange = ()=>{
    if(['failed','disconnected','closed'].includes(pc.connectionState))
      delete peerConnections[viewerChannel];
  };

  await pc.setRemoteDescription(new RTCSessionDescription({type:'offer',sdp}));
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);

  ws?.readyState===1 && ws.send(JSON.stringify({
    type:'answer',sdp:answer.sdp,peer_id:viewerChannel,
  }));

  await applyBitrateCap(pc);
  // Re-balance everyone else too, since the viewer count just changed
  Object.values(peerConnections).forEach(applyBitrateCap);
}

// ── CHAT ──────────────────────────────────────────────────
function sendChat() {
  const m1 = document.getElementById('chat-input');
  const m2 = document.getElementById('desktop-chat-input');
  const msg = (m1?.value||m2?.value||'').trim();
  if(!msg || ws?.readyState!==1) return;
  ws.send(JSON.stringify({type:'chat',message:msg}));
  if(m1) m1.value='';
  if(m2) m2.value='';
}

function appendChat(data) {
  const isVendor = data.is_vendor;
  chatCount++;
  const badge = document.getElementById('chat-badge');
  if(badge) badge.textContent = chatCount;

  // Mobile overlay
  const mBox = document.getElementById('chat-messages');
  const mDiv = document.createElement('div');
  mDiv.className = 'chat-bubble';
  mDiv.innerHTML = `
    <div style="width:26px;height:26px;border-radius:50%;flex-shrink:0;background:${isVendor?'#F5A623':'rgba(255,255,255,.15)'};display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:${isVendor?'#0F1B2D':'white'};">
      ${data.initials||'?'}
    </div>
    <div class="chat-bg">
      <span style="font-size:11px;font-weight:700;color:${isVendor?'#F5A623':'rgba(255,255,255,.8)'};">${isVendor?'🏪 ':''}${esc(data.username)}</span>
      <span style="font-size:13px;color:white;margin-left:4px;">${esc(data.message)}</span>
    </div>`;
  mBox.appendChild(mDiv);
  mBox.scrollTop = mBox.scrollHeight;
  while(mBox.children.length>60) mBox.removeChild(mBox.children[0]);

  // Desktop side
  const dBox = document.getElementById('desktop-chat');
  if(dBox){
    const dDiv = document.createElement('div');
    dDiv.style.cssText='display:flex;align-items:flex-start;gap:8px;';
    dDiv.innerHTML=`
      <div style="width:28px;height:28px;border-radius:50%;flex-shrink:0;background:${isVendor?'#F5A623':'rgba(255,255,255,.1)'};display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:${isVendor?'#0F1B2D':'white'};">
        ${data.initials||'?'}
      </div>
      <div style="flex:1;min-width:0;">
        <span style="font-size:11px;font-weight:700;color:${isVendor?'#F5A623':'#d1d5db'};">${isVendor?'🏪 ':''}${esc(data.username)}</span>
        ${isVendor?'<span style="font-size:9px;background:#F5A623;color:#0F1B2D;font-weight:700;padding:1px 5px;border-radius:99px;margin-left:4px;">YOU</span>':''}
        <p style="font-size:13px;color:white;margin:2px 0 0;word-break:break-word;">${esc(data.message)}</p>
      </div>`;
    dBox.appendChild(dDiv);
    dBox.scrollTop = dBox.scrollHeight;
    while(dBox.children.length>80) dBox.removeChild(dBox.children[0]);
  }
}

// ── GIFTS ─────────────────────────────────────────────────
function handleGift(data) {
  totalGifts += parseFloat(data.total_value||0);
  document.getElementById('gift-total').textContent = totalGifts.toFixed(2);
  floatEmoji(data.emoji||'🎁');
  floatEmoji(data.emoji||'🎁');
  appendSystemMsg(`🎁 ${esc(data.username||'Someone')} sent ${data.emoji} (GHS ${data.total_value||0})`);
}

// ── LIVE POLL (new) ────────────────────────────────────────
let activePoll = null; // { question, options: {a: {label, votes}, b: {label, votes}} }

function closePollSheet() {
  document.getElementById('poll-backdrop').style.display = 'none';
  document.getElementById('poll-sheet').classList.remove('open');
}

function startPoll() {
  const question = document.getElementById('poll-question-input').value.trim();
  const labelA   = document.getElementById('poll-option-a-input').value.trim() || 'Option A';
  const labelB   = document.getElementById('poll-option-b-input').value.trim() || 'Option B';
  if (!question) {
    const inp = document.getElementById('poll-question-input');
    if (inp) { inp.style.borderColor='#ef4444'; inp.focus(); }
    return;
  }

  activePoll = { question, options: { a: { label: labelA, votes: 0 }, b: { label: labelB, votes: 0 } } };
  document.getElementById('poll-question').textContent = question;
  document.getElementById('poll-label-a').textContent = labelA;
  document.getElementById('poll-label-b').textContent = labelB;
  updatePollDisplay();
  document.getElementById('live-poll-widget').classList.add('show');
  closePollSheet();

  ws?.readyState === 1 && ws.send(JSON.stringify({
    type: 'poll_start', question, options: { a: labelA, b: labelB },
  }));
}

function recordPollVote(option) {
  if (!activePoll || !activePoll.options[option]) return;
  activePoll.options[option].votes++;
  updatePollDisplay();
}

function updatePollDisplay() {
  if (!activePoll) return;
  const a = activePoll.options.a.votes, b = activePoll.options.b.votes;
  const total = a + b || 1;
  const pctA = Math.round((a / total) * 100), pctB = 100 - pctA;
  document.getElementById('poll-fill-a').style.width = pctA + '%';
  document.getElementById('poll-fill-b').style.width = pctB + '%';
  document.getElementById('poll-pct-a').textContent = pctA + '% (' + a + ')';
  document.getElementById('poll-pct-b').textContent = pctB + '% (' + b + ')';
}

function endPoll() {
  ws?.readyState === 1 && ws.send(JSON.stringify({ type: 'poll_end' }));
  document.getElementById('live-poll-widget').classList.remove('show');
  activePoll = null;
}

// ── PIN PRODUCT ───────────────────────────────────────────
function closePinSheet() {
  document.getElementById('pin-backdrop').style.display = 'none';
  document.getElementById('pin-sheet').classList.remove('open');
}

async function pinProduct(productId, btn) {
  const action = currentPinnedId === productId ? 'unpin' : 'pin';
  try {
    const res  = await fetch(PIN_URL,{
      method:'POST',
      headers:{'Content-Type':'application/json','X-CSRFToken':CSRF_TOKEN},
      body:JSON.stringify({product_id:productId,action}),
    });
    const data = await res.json();
    if(!data.success) return;

    document.querySelectorAll('.pin-btn').forEach(b=>{
      b.style.borderColor='rgba(255,255,255,.08)';
      b.style.background='rgba(255,255,255,.05)';
      b.querySelector('.pin-label').textContent='Pin';
      b.querySelector('.pin-label').style.color='#6b7280';
    });

    if(data.action==='pinned'){
      currentPinnedId = productId;
      btn.style.borderColor = '#F5A623';
      btn.style.background  = 'rgba(245,166,35,.08)';
      const lbl = btn.querySelector('.pin-label');
      lbl.textContent='✓ Pinned';lbl.style.color='#F5A623';
      showPinnedBar({
        name:btn.dataset.name, price:btn.dataset.price,
        image:btn.dataset.image, slug:btn.dataset.slug,
      });
    } else {
      currentPinnedId = null;
      document.getElementById('pinned-bar').style.display='none';
    }
    closePinSheet();
  } catch(e){console.error('Pin error:',e);}
}

function showPinnedBar(product) {
  const bar   = document.getElementById('pinned-bar');
  const img   = document.getElementById('pin-preview-img');
  const name  = document.getElementById('pin-preview-name');
  const price = document.getElementById('pin-preview-price');
  if(!bar) return;
  if(img)   img.src           = product.image||'';
  if(name)  name.textContent  = product.name||'';
  if(price) price.textContent = `GHS ${product.price||product.selling_price||''}`;
  bar.style.display='block';
}

// ── END STREAM ────────────────────────────────────────────
function confirmEnd() {
  document.getElementById('end-modal').style.display = 'flex';
}

async function endStream() {
  const btn = document.getElementById('end-stream-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Ending stream…'; }

  // 1. Tell WebSocket the stream is ending (broadcasts to all viewers)
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'end_stream' }));
  }

  // 2. Null localStream BEFORE closing WS — prevents auto-reconnect
  const streamToStop = localStream;
  localStream = null;

  // 3. Upload recording (max 25s wait, see stopRecordingAndUpload)
  if (btn) btn.textContent = '⏳ Saving replay…';
  const recordingUrl = await stopRecordingAndUpload();

  // 4. Stop all tracks and peer connections
  streamToStop?.getTracks().forEach(t => t.stop());
  Object.values(peerConnections).forEach(pc => pc.close());
  peerConnections = {};
  clearInterval(timerInterval);

  // 5. Close WebSocket cleanly
  try { ws?.close(1000, 'Stream ended'); } catch(e) {}

  // 6. Tell the server the stream has ended (saves peak_viewers, recording_url)
  try {
    const res = await fetch(END_URL, {
      method:  'POST',
      headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
      body:    JSON.stringify({ peak_viewers: peakViewers, recording_url: recordingUrl }),
    });
    const data = await res.json();

    // 7. Show in-page summary (no alert!)
    if (data.success) {
      const modal = document.getElementById('end-modal');
      if (modal) {
        modal.innerHTML = `
          <div style="background:#1a1a1a;border-radius:24px;padding:28px;max-width:360px;width:100%;text-align:center;border:1px solid #333;">
            <p style="font-size:44px;margin-bottom:12px">🎉</p>
            <p style="color:white;font-weight:700;font-size:18px;margin-bottom:16px">Stream Ended!</p>
            <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:24px;">
              <div style="background:rgba(255,255,255,.06);border-radius:12px;padding:10px 14px;display:flex;justify-content:space-between;">
                <span style="color:rgba(255,255,255,.6);font-size:13px;">Peak viewers</span>
                <span style="color:white;font-weight:700;">${peakViewers}</span>
              </div>
              <div style="background:rgba(255,255,255,.06);border-radius:12px;padding:10px 14px;display:flex;justify-content:space-between;">
                <span style="color:rgba(255,255,255,.6);font-size:13px;">Gifts received</span>
                <span style="color:#4ade80;font-weight:700;">GHS ${data.gifts_value || '0.00'}</span>
              </div>
              <div style="background:rgba(255,255,255,.06);border-radius:12px;padding:10px 14px;display:flex;justify-content:space-between;">
                <span style="color:rgba(255,255,255,.6);font-size:13px;">Duration</span>
                <span style="color:white;font-weight:700;">${data.duration || 0} mins</span>
              </div>
              ${recordingUrl ? '<div style="color:#4ade80;font-size:12px;margin-top:4px;">✅ Replay saved</div>' : '<div style="color:#9ca3af;font-size:12px;margin-top:4px;">Replay not saved</div>'}
            </div>
            <button onclick="window.location.href=window.VENDOR_DASHBOARD_URL||'/vendors/dashboard/'"
                    style="width:100%;background:#F5A623;border:none;border-radius:14px;color:#0F1B2D;font-weight:700;padding:14px;cursor:pointer;font-size:15px;">
              Back to Dashboard →
            </button>
          </div>`;
      } else {
        window.location.href = window.VENDOR_DASHBOARD_URL || '/vendors/dashboard/';
      }
    } else {
      window.location.href = window.VENDOR_DASHBOARD_URL || '/vendors/dashboard/';
    }
  } catch(e) {
    console.error('[endStream]', e);
    window.location.href = window.VENDOR_DASHBOARD_URL || '/vendors/dashboard/';
  }
}

// ── HELPERS ───────────────────────────────────────────────
function floatEmoji(emoji) {
  const el  = document.createElement('div');
  el.className = 'like-float';
  el.textContent = emoji;
  el.style.left   = 5+Math.random()*30+'%';
  el.style.bottom = '120px';
  document.body.appendChild(el);
  setTimeout(()=>el.remove(),2500);
}

function appendSystemMsg(text) {
  const box = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.style.cssText='text-align:left;padding:2px 0;';
  div.innerHTML=`<span style="font-size:11px;color:rgba(255,255,255,.4);background:rgba(0,0,0,.3);padding:3px 10px;border-radius:99px;">${text}</span>`;
  box.appendChild(div);
  box.scrollTop=box.scrollHeight;
}

function esc(str){
  return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function startTimer() {
  timerInterval = setInterval(()=>{
    const s=Math.floor((Date.now()-startTime)/1000);
    const m=String(Math.floor(s/60)).padStart(2,'0');
    const sec=String(s%60).padStart(2,'0');
    document.getElementById('timer').textContent=`${m}:${sec}`;
  },1000);
}

// Confirm JS loaded correctly
console.log('[livestream.js] ✓ Loaded — STREAM_ID:', STREAM_ID, '| startCamera:', typeof startCamera);

// ── Camera button failsafe (addEventListener as backup for onclick) ────────────
// Some iOS browsers ignore onclick on elements inside fixed/absolute containers.
// Adding a direct event listener guarantees the tap is captured.
(function () {
  var btn = document.getElementById('start-cam-btn');
  if (!btn) {
    // Fallback: find button by text content
    var btns = document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
      if (btns[i].textContent.includes('Start Camera')) { btn = btns[i]; break; }
    }
  }
  if (btn) {
    btn.addEventListener('touchend', function(e) {
      e.preventDefault();
      startCamera();
    }, { passive: false });
    btn.addEventListener('click', function(e) {
      startCamera();
    });
    console.log('[camera] Start Camera button wired via addEventListener ✓');
  } else {
    console.warn('[camera] Start Camera button not found');
  }
})();

// Restore pinned state — PINNED_IDS supplied by broadcast.html as window.PINNED_IDS
(function () {
  const ids = window.PINNED_IDS || [];
  if (!ids.length) return;
  currentPinnedId = ids[ids.length - 1];
  ids.forEach(function (pid) {
    const btn = document.querySelector('[data-id="' + pid + '"]');
    if (!btn) return;
    btn.style.borderColor = '#F5A623';
    btn.style.background  = 'rgba(245,166,35,.08)';
    const lbl = btn.querySelector('.pin-label');
    if (lbl) { lbl.textContent = '✓ Pinned'; lbl.style.color = '#F5A623'; }
  });
})();

window.addEventListener('beforeunload', e=>{
  if(localStream){e.preventDefault();e.returnValue='Your stream is live. Leave?';}
});