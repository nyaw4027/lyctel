/*
  static/js/rider_alert.js
  Add <script src="{% static 'js/rider_alert.js' %}"></script> to base.html
  (inside {% block extra_js %} or before </body>)

  Listens for PLAY_RIDER_ALERT message from service worker and plays
  a beep sound using the Web Audio API — no external audio file needed.
*/
(function() {
  if (!navigator.serviceWorker) return;

  navigator.serviceWorker.addEventListener('message', function(event) {
    if (event.data && event.data.type === 'PLAY_RIDER_ALERT') {
      playAlertSound();
    }
  });

  function playAlertSound() {
    try {
      var ctx = new (window.AudioContext || window.webkitAudioContext)();

      // Two-tone alert: 880Hz + 660Hz
      [880, 660, 880].forEach(function(freq, i) {
        var osc  = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.type      = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0, ctx.currentTime + i * 0.18);
        gain.gain.linearRampToValueAtTime(0.4, ctx.currentTime + i * 0.18 + 0.02);
        gain.gain.linearRampToValueAtTime(0,   ctx.currentTime + i * 0.18 + 0.16);

        osc.start(ctx.currentTime + i * 0.18);
        osc.stop(ctx.currentTime + i * 0.18 + 0.18);
      });
    } catch(e) {
      console.warn('Could not play alert sound:', e);
    }
  }

  // Also expose globally so admin pages can call it directly
  window.playRiderAlert = playAlertSound;
})();