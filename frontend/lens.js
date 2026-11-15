/* =========================================================
   8search – in-app visual search (Lens-style camera)
   ========================================================= */

(function () {
  'use strict';

  // ---------- DOM ----------
  var modal            = document.getElementById('lensModal');
  if (!modal) return;

  var backdrop         = document.getElementById('lensBackdrop');
  var closeBtn         = document.getElementById('lensCloseBtn');
  var video            = document.getElementById('lensVideo');
  var preview          = document.getElementById('lensPreview');
  var canvas           = document.getElementById('lensCanvas');
  var scanFrame        = document.getElementById('lensScanFrame');
  var statusEl         = document.getElementById('lensStatus');
  var progressEl       = document.getElementById('lensProgress');
  var progressBar      = document.getElementById('lensProgressBar');
  var cameraControls   = document.getElementById('lensCameraControls');
  var captureActions   = document.getElementById('lensCaptureActions');
  var cameraError      = document.getElementById('lensCameraError');
  var cameraErrorText  = document.getElementById('lensCameraErrorText');
  var fileInput        = document.getElementById('lensFileInput');
  var panelEmpty       = document.getElementById('lensPanelEmpty');
  var resultEl         = document.getElementById('lensResult');
  var toastEl          = document.getElementById('lensToast');
  var shutterBtn       = document.getElementById('lensShutterBtn');
  var switchBtn        = document.getElementById('lensSwitchBtn');
  var torchBtn         = document.getElementById('lensTorchBtn');
  var uploadBtn        = document.getElementById('lensUploadBtn');
  var uploadTopBtn     = document.getElementById('lensUploadTop');
  var errorUploadBtn   = document.getElementById('lensErrorUploadBtn');
  var retakeBtn        = document.getElementById('lensRetakeBtn');
  var newScanBtn       = document.getElementById('lensNewScanBtn');
  var typeBtn          = document.getElementById('lensTypeBtn');

  // ---------- State ----------
  var stream           = null;
  var facingMode       = 'environment';
  var scanTimer        = null;
  var scanBusy         = false;
  var detector         = null;
  var torchOn          = false;
  var busy             = false;
  var opened           = false;
  var tesseractWorker  = null;
  var tesseractPromise = null;
  var toastTimer       = null;
  var resultState      = null;
  var userChangedTab   = false;

  var scanCanvas = document.createElement('canvas');
  var scanCtx = scanCanvas.getContext('2d', { willReadFrequently: true });

  var LANGUAGES = [
    ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
    ['hi', 'Hindi'], ['ar', 'Arabic'], ['zh-CN', 'Chinese (Simplified)'],
    ['ja', 'Japanese'], ['ko', 'Korean'], ['pt', 'Portuguese'],
    ['ru', 'Russian'], ['it', 'Italian'], ['tr', 'Turkish'],
    ['id', 'Indonesian'], ['vi', 'Vietnamese'], ['th', 'Thai'],
    ['bn', 'Bengali'], ['ur', 'Urdu'], ['nl', 'Dutch'], ['pl', 'Polish'],
    ['uk', 'Ukrainian'], ['fa', 'Persian'], ['he', 'Hebrew'],
    ['ta', 'Tamil'], ['te', 'Telugu'], ['mr', 'Marathi'], ['gu', 'Gujarati'],
    ['pa', 'Punjabi'], ['sw', 'Swahili']
  ];

  // ---------- Small helpers ----------
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function escapeAttr(value) { return escapeHtml(value); }

  function setStatus(message) {
    if (statusEl) statusEl.textContent = message || '';
  }

  function showToast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.remove('hidden');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toastEl.classList.add('hidden');
    }, 2600);
  }

  function setProgress(value) {
    if (!progressEl || !progressBar) return;
    if (value == null) {
      progressEl.classList.add('hidden');
      progressBar.style.width = '0%';
      return;
    }
    progressEl.classList.remove('hidden');
    progressBar.style.width = Math.max(0, Math.min(100, Math.round(value * 100))) + '%';
  }

  function stopScanLoop() {
    if (scanTimer) {
      window.clearInterval(scanTimer);
      scanTimer = null;
    }
    scanBusy = false;
  }

  function stopCamera() {
    stopScanLoop();
    if (stream) {
      stream.getTracks().forEach(function (track) {
        try { track.stop(); } catch (e) {}
      });
      stream = null;
    }
    if (video) video.srcObject = null;
    torchOn = false;
    if (torchBtn) {
      torchBtn.classList.remove('active');
      torchBtn.hidden = true;
    }
  }

  function videoReady() {
    return video && video.readyState >= 2 && video.videoWidth > 0;
  }

  // ---------- Camera ----------
  async function startCamera() {
    stopCamera();
    resetCaptureView();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showCameraError('This browser does not support camera access. Upload a photo instead.');
      return;
    }

    busy = true;
    setStatus('Starting camera…');
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: facingMode },
          width: { ideal: 1920 },
          height: { ideal: 1080 }
        }
      });
      video.srcObject = stream;
      video.classList.remove('hidden');
      preview.classList.add('hidden');
      await video.play().catch(function () {});
      cameraError.classList.add('hidden');
      cameraControls.classList.remove('hidden');
      captureActions.classList.add('hidden');
      scanFrame.classList.remove('hidden');
      busy = false;
      setStatus('Point your camera at a QR code, a sign, or a question.');
      setupDetector();
      startScanLoop();
      checkTorch();
    } catch (err) {
      busy = false;
      var message = 'Allow camera access in your browser, or upload a photo instead.';
      if (err && err.name === 'NotAllowedError') {
        message = 'Camera access was blocked. Allow it in your browser settings, or upload a photo instead.';
      } else if (err && err.name === 'NotFoundError') {
        message = 'No camera was found on this device. Upload a photo instead.';
      } else if (err && err.name === 'NotReadableError') {
        message = 'The camera is already in use by another app. Close it and try again.';
      }
      showCameraError(message);
    }
  }

  function showCameraError(message) {
    stopScanLoop();
    if (video) video.classList.add('hidden');
    if (preview) preview.classList.add('hidden');
    if (scanFrame) scanFrame.classList.add('hidden');
    if (cameraControls) cameraControls.classList.add('hidden');
    if (captureActions) captureActions.classList.add('hidden');
    if (cameraError) cameraError.classList.remove('hidden');
    if (cameraErrorText) cameraErrorText.textContent = message;
    setStatus('Camera unavailable');
  }

  function resetCaptureView() {
    busy = false;
    if (preview) {
      preview.classList.add('hidden');
      preview.removeAttribute('src');
    }
    if (video) video.classList.remove('hidden');
    if (cameraError) cameraError.classList.add('hidden');
    if (scanFrame) scanFrame.classList.remove('hidden');
    if (cameraControls) cameraControls.classList.remove('hidden');
    if (captureActions) captureActions.classList.add('hidden');
    setProgress(null);
  }

  function checkTorch() {
    if (!torchBtn || !stream) return;
    var track = stream.getVideoTracks()[0];
    var caps = track && track.getCapabilities ? track.getCapabilities() : {};
    torchBtn.hidden = !(caps && caps.torch);
  }

  async function toggleTorch() {
    if (!stream) return;
    var track = stream.getVideoTracks()[0];
    if (!track || !track.applyConstraints) return;
    torchOn = !torchOn;
    try {
      await track.applyConstraints({ advanced: [{ torch: torchOn }] });
      torchBtn.classList.toggle('active', torchOn);
      torchBtn.setAttribute('aria-label', torchOn ? 'Turn off flashlight' : 'Turn on flashlight');
    } catch (e) {
      torchOn = false;
      showToast('Flashlight is not available on this camera.');
    }
  }

  function switchCamera() {
    if (busy) return;
    facingMode = facingMode === 'environment' ? 'user' : 'environment';
    startCamera();
  }

  function setupDetector() {
    if (!('BarcodeDetector' in window) || detector) return;
    var formats = [
      'qr_code', 'ean_13', 'ean_8', 'code_128', 'code_39',
      'upc_a', 'upc_e', 'pdf417', 'aztec', 'data_matrix'
    ];
    try {
      detector = new window.BarcodeDetector({ formats: formats });
    } catch (e) {
      try {
        detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      } catch (err) {
        detector = null;
      }
    }
  }

  function startScanLoop() {
    stopScanLoop();
    if (!detector && !window.jsQR) return;
    scanTimer = window.setInterval(scanTick, 320);
  }

  async function scanTick() {
    if (scanBusy || busy || !opened || !videoReady()) return;
    scanBusy = true;
    try {
      var width = video.videoWidth;
      var height = video.videoHeight;
      var scale = Math.min(1, 1100 / Math.max(width, height));
      scanCanvas.width = Math.max(1, Math.round(width * scale));
      scanCanvas.height = Math.max(1, Math.round(height * scale));
      scanCtx.drawImage(video, 0, 0, scanCanvas.width, scanCanvas.height);

      var code = await detectCode(scanCanvas);
      if (code) {
        await handleCode(code.rawValue || code.data || '', code.format || 'qr_code');
      }
    } catch (e) {
      // Camera frames can fail while the stream is changing; keep scanning.
    } finally {
      scanBusy = false;
    }
  }

  async function detectCode(source) {
    if (detector) {
      try {
        var codes = await detector.detect(source);
        if (codes && codes.length) return codes[0];
        return null;
      } catch (e) {
        // Fall through to jsQR if the native detector rejects this frame.
      }
    }
    if (window.jsQR) {
      var width = source.width;
      var height = source.height;
      var context = source.getContext('2d', { willReadFrequently: true });
      var image = context.getImageData(0, 0, width, height);
      var found = window.jsQR(image.data, width, height, {
        inversionAttempts: 'attemptBoth'
      });
      if (found && found.data) {
        return { rawValue: found.data, format: 'qr_code' };
      }
    }
    return null;
  }

  // ---------- Capture ----------
  function drawToCanvas(source, maxDimension) {
    var width = source.videoWidth || source.naturalWidth || source.width;
    var height = source.videoHeight || source.naturalHeight || source.height;
    if (!width || !height) return false;
    var scale = Math.min(1, (maxDimension || 1600) / Math.max(width, height));
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    var ctx = canvas.getContext('2d');
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    return true;
  }

  async function capturePhoto() {
    if (busy || !videoReady()) {
      if (!busy) showToast('Wait for the camera to finish starting.');
      return;
    }
    busy = true;
    stopScanLoop();
    if (!drawToCanvas(video, 1600)) {
      busy = false;
      showToast('The camera frame was empty. Try again.');
      startScanLoop();
      return;
    }
    var dataUrl = canvas.toDataURL('image/jpeg', 0.92);
    showCapturedFrame(dataUrl);
    setStatus('Reading the photo…');
    await processCanvas(canvas);
  }

  function showCapturedFrame(dataUrl) {
    preview.src = dataUrl;
    preview.classList.remove('hidden');
    video.classList.add('hidden');
    scanFrame.classList.add('hidden');
    cameraControls.classList.add('hidden');
    captureActions.classList.remove('hidden');
  }

  async function processCanvas(sourceCanvas) {
    busy = true;
    resultEl.classList.add('hidden');
    panelEmpty.classList.add('hidden');
    var code = await detectCode(sourceCanvas);
    if (code) {
      await handleCode(code.rawValue || code.data || '', code.format || 'qr_code');
      return;
    }
    await recogniseText(sourceCanvas.toDataURL('image/jpeg', 0.92));
  }

  // ---------- QR / barcode ----------
  function parseQrValue(value) {
    var raw = String(value || '').trim();
    if (!raw) return { kind: 'text', text: 'Empty QR code' };

    var wifi = raw.match(/^WIFI:([^;]*);?/i);
    if (wifi) {
      var fields = {};
      wifi[1].split(';').forEach(function (part) {
        if (!part) return;
        var index = part.indexOf(':');
        if (index > 0) fields[part.slice(0, index).toUpperCase()] = part.slice(index + 1);
      });
      return {
        kind: 'wifi',
        ssid: fields.S || '',
        password: fields.P || '',
        security: fields.T || '',
        text: raw
      };
    }

    if (/^BEGIN:VCARD/i.test(raw)) {
      var name = raw.match(/\nFN:(.*)/i);
      return { kind: 'contact', text: raw, label: name ? name[1].trim() : 'Contact card' };
    }

    if (/^https?:\/\//i.test(raw)) return { kind: 'url', url: raw, text: raw };
    if (/^www\./i.test(raw)) return { kind: 'url', url: 'https://' + raw, text: raw };
    if (/^mailto:/i.test(raw)) return { kind: 'link', url: raw, text: raw };
    if (/^tel:/i.test(raw)) return { kind: 'link', url: raw, text: raw };
    if (/^sms:/i.test(raw)) return { kind: 'link', url: raw, text: raw };
    if (/^geo:/i.test(raw)) return { kind: 'link', url: raw, text: raw };

    return { kind: 'text', text: raw };
  }

  async function handleCode(value, format) {
    stopScanLoop();
    busy = false;
    setStatus('QR code detected');
    setProgress(null);
    if (!preview || preview.classList.contains('hidden')) {
      if (videoReady()) {
        drawToCanvas(video, 1400);
        showCapturedFrame(canvas.toDataURL('image/jpeg', 0.92));
      }
    }
    resultState = { kind: 'qr', qr: parseQrValue(value), format: format };
    renderResult();
  }

  function renderQrResult() {
    var qr = resultState.qr;
    var title = 'QR code';
    var detail = '';
    var action = '';

    if (qr.kind === 'url') {
      title = 'Open this link';
      detail = '<p class="lens-qr-url">' + escapeHtml(qr.url) + '</p>';
      action = '<a class="lens-primary-link" href="' + escapeAttr(qr.url) + '" target="_blank" rel="noopener noreferrer">Open link</a>';
    } else if (qr.kind === 'wifi') {
      title = 'Wi-Fi network';
      detail =
        '<div class="lens-kv"><span>Network</span><strong>' + escapeHtml(qr.ssid || 'Hidden network') + '</strong></div>' +
        (qr.security ? '<div class="lens-kv"><span>Security</span><strong>' + escapeHtml(qr.security) + '</strong></div>' : '') +
        (qr.password ? '<div class="lens-kv"><span>Password</span><strong class="lens-secret">' + escapeHtml(qr.password) + '</strong></div>' : '');
      action = qr.password
        ? '<button type="button" class="lens-primary" data-lens-action="copy" data-value="' + escapeAttr(qr.password) + '">Copy password</button>'
        : '';
    } else if (qr.kind === 'contact') {
      title = qr.label || 'Contact card';
      detail = '<pre class="lens-pre">' + escapeHtml(qr.text) + '</pre>';
      action = '<button type="button" class="lens-primary" data-lens-action="copy" data-value="' + escapeAttr(qr.text) + '">Copy contact</button>';
    } else if (qr.kind === 'link') {
      title = 'Open this action';
      detail = '<p class="lens-qr-url">' + escapeHtml(qr.text) + '</p>';
      action = '<a class="lens-primary-link" href="' + escapeAttr(qr.url) + '">Open</a>';
    } else {
      title = 'QR text';
      detail = '<pre class="lens-pre">' + escapeHtml(qr.text) + '</pre>';
      action = '<button type="button" class="lens-primary" data-lens-action="copy" data-value="' + escapeAttr(qr.text) + '">Copy text</button>';
    }

    return '' +
      '<div class="lens-result-head">' +
        '<p class="lens-result-kicker">' + escapeHtml((resultState.format || 'QR').replace(/_/g, ' ')) + '</p>' +
        '<h2>' + escapeHtml(title) + '</h2>' +
      '</div>' +
      '<div class="lens-qr-card">' +
        '<div class="lens-qr-icon">' + qrIcon() + '</div>' +
        detail +
      '</div>' +
      '<div class="lens-result-actions">' +
        action +
        '<button type="button" class="lens-secondary" data-lens-action="new-scan">Scan another</button>' +
      '</div>';
  }

  function qrIcon() {
    return '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      '<rect x="3" y="3" width="6" height="6" rx="1"></rect><rect x="15" y="3" width="6" height="6" rx="1"></rect>' +
      '<rect x="3" y="15" width="6" height="6" rx="1"></rect><path d="M15 15h2v2h-2zM19 19h2v2h-2zM15 19h2M19 15h2"></path></svg>';
  }

  // ---------- OCR ----------
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var existing = document.querySelector('script[data-lens-src="' + src + '"]');
      if (existing) {
        if (existing.dataset.loaded === '1') return resolve();
        existing.addEventListener('load', function () { resolve(); });
        existing.addEventListener('error', function () { reject(new Error('load failed')); });
        return;
      }
      var script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.setAttribute('data-lens-src', src);
      script.addEventListener('load', function () {
        script.dataset.loaded = '1';
        resolve();
      });
      script.addEventListener('error', function () { reject(new Error('load failed')); });
      document.head.appendChild(script);
    });
  }

  async function getTesseractWorker() {
    if (tesseractWorker) return tesseractWorker;
    if (!tesseractPromise) {
      tesseractPromise = (async function () {
        await loadScript('https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js');
        if (!window.Tesseract) throw new Error('Tesseract did not load');
        return window.Tesseract.createWorker('eng', 1, {
          logger: function (message) {
            if (!message) return;
            if (message.status === 'recognizing text') {
              setProgress(message.progress || 0);
            }
          }
        });
      })();
    }
    try {
      tesseractWorker = await tesseractPromise;
      return tesseractWorker;
    } catch (err) {
      tesseractPromise = null;
      throw err;
    }
  }

  function cleanOcrText(text) {
    return String(text || '')
      .replace(/\r\n?/g, '\n')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
  }

  async function recogniseText(dataUrl) {
    busy = true;
    setStatus('Reading the photo…');
    setProgress(0.04);
    resultState = { kind: 'ocr', text: '', active: 'text', ocrStatus: 'loading', solveStatus: 'loading', searchStatus: 'idle', translateStatus: 'idle', solve: null, search: null, translation: null };
    renderResult();

    try {
      var worker = await getTesseractWorker();
      setStatus('Recognising text…');
      var result = await worker.recognize(dataUrl);
      var text = cleanOcrText(result && result.data ? result.data.text : '');
      busy = false;
      setProgress(null);
      setStatus('Photo analysed');
      if (!text) {
        resultState = { kind: 'empty' };
        renderResult();
        return;
      }
      resultState.text = text;
      resultState.ocrStatus = 'done';
      var autoSearch = shouldAutoSearch(text);
      resultState.active = shouldOpenHomework(text)
        ? 'homework'
        : (autoSearch ? 'search' : 'text');
      renderResult();
      loadSolve(text);
      if (autoSearch) loadSearch(text, true);
    } catch (err) {
      busy = false;
      setProgress(null);
      setStatus('Could not read the photo');
      resultState = {
        kind: 'error',
        message: 'Text recognition could not start. Check your internet connection and try again.'
      };
      renderResult();
    }
  }

  function shouldOpenHomework(text) {
    return /[0-9]/.test(text) && /[=+\-*/^]/.test(text);
  }

  function shouldAutoSearch(text) {
    var t = text.trim();
    if (!t || t.length < 4) return false;
    if (shouldOpenHomework(t)) return false;
    return /\?\s*$/.test(t) ||
      /^(?:what|who|where|when|why|how|which|define|explain|describe|tell me|is |are |can |do |does |did )/i.test(t);
  }

  async function loadSolve(text) {
    if (!resultState || resultState.kind !== 'ocr') return;
    if (resultState.solveStatus === 'done') return;
    resultState.solveStatus = 'loading';
    if (resultState.active === 'homework') renderBody();
    try {
      var response = await fetch('/api/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ expression: text.slice(0, 780) })
      });
      var data = await response.json().catch(function () { return {}; });
      if (!response.ok) throw new Error(data.detail || 'The solver is unavailable.');
      resultState.solve = data;
      resultState.solveStatus = 'done';
      if (data.solved) {
        if (!userChangedTab && resultState.active !== 'homework') {
          resultState.active = 'homework';
        }
        renderResult();
      } else if (resultState.active === 'homework') {
        renderBody();
      }
    } catch (err) {
      resultState.solveStatus = 'error';
      resultState.solveError = err && err.message ? err.message : 'The solver is unavailable.';
      if (resultState.active === 'homework') renderBody();
    }
  }

  async function loadSearch(text, auto) {
    if (!resultState || resultState.kind !== 'ocr') return;
    if (resultState.searchStatus === 'loading') return;
    if (resultState.searchStatus === 'done' && !auto) return;

    var query = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 360);
    if (!query) return;
    resultState.searchStatus = 'loading';
    resultState.searchError = '';
    resultState.searchQuery = query;
    if (resultState.active === 'search') renderBody();

    try {
      var response = await fetch('/api/search?q=' + encodeURIComponent(query) + '&page=1',
        { credentials: 'same-origin' });
      var data = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        throw new Error(data.detail || 'Search is temporarily unavailable.');
      }
      resultState.search = data;
      resultState.searchStatus = 'done';
      if (resultState.active === 'search') renderBody();
    } catch (err) {
      resultState.searchStatus = 'error';
      resultState.searchError = err && err.message ? err.message : 'Search is temporarily unavailable.';
      if (resultState.active === 'search') renderBody();
    }
  }

  async function translateText(text, target) {
    if (!resultState || resultState.kind !== 'ocr') return;
    resultState.translation = null;
    resultState.translateStatus = 'loading';
    resultState.translateError = '';
    renderBody();
    try {
      var response = await fetch('/api/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ text: text.slice(0, 4800), target: target, source: 'auto' })
      });
      var data = await response.json().catch(function () { return {}; });
      if (!response.ok) throw new Error(data.detail || 'Translation is temporarily unavailable.');
      resultState.translation = data;
      resultState.translateStatus = 'done';
      resultState.translateTarget = target;
      renderBody();
    } catch (err) {
      resultState.translateStatus = 'error';
      resultState.translateError = err && err.message ? err.message : 'Translation is temporarily unavailable.';
      renderBody();
    }
  }

  // ---------- Results panel ----------
  function resetResult() {
    resultState = null;
    userChangedTab = false;
    busy = false;
    setProgress(null);
    if (resultEl) {
      resultEl.classList.add('hidden');
      resultEl.innerHTML = '';
    }
    if (panelEmpty) panelEmpty.classList.remove('hidden');
    setStatus('Point your camera at a QR code, a sign, or a question.');
  }

  function renderResult() {
    if (!resultEl || !panelEmpty) return;
    panelEmpty.classList.add('hidden');
    resultEl.classList.remove('hidden');
    if (!resultState) {
      resultEl.classList.add('hidden');
      panelEmpty.classList.remove('hidden');
      return;
    }

    if (resultState.kind === 'qr') {
      resultEl.innerHTML = renderQrResult();
      return;
    }
    if (resultState.kind === 'empty') {
      resultEl.innerHTML = '' +
        '<div class="lens-result-head"><p class="lens-result-kicker">No text found</p><h2>Move a little closer</h2></div>' +
        '<p class="lens-copy">We could not read any text in this photo. Keep the page flat, fill the frame, and avoid glare.</p>' +
        '<div class="lens-result-actions"><button type="button" class="lens-primary" data-lens-action="new-scan">Try again</button></div>';
      return;
    }
    if (resultState.kind === 'error') {
      resultEl.innerHTML = '' +
        '<div class="lens-result-head"><p class="lens-result-kicker">Camera result</p><h2>Something went wrong</h2></div>' +
        '<p class="lens-copy">' + escapeHtml(resultState.message || 'Try another photo.') + '</p>' +
        '<div class="lens-result-actions"><button type="button" class="lens-primary" data-lens-action="new-scan">Try again</button></div>';
      return;
    }

    resultEl.innerHTML = renderOcrFrame();
  }

  function resultTabs() {
    return [
      { id: 'search', label: 'Search' },
      { id: 'text', label: 'Text' },
      { id: 'homework', label: 'Homework' },
      { id: 'translate', label: 'Translate' }
    ];
  }

  function renderOcrFrame() {
    var tabs = resultTabs();
    var active = resultState.active || 'text';
    var solveReady = resultState.solveStatus === 'done' && resultState.solve && resultState.solve.solved;

    var tabHtml = tabs.map(function (tab) {
      var label = tab.label;
      if (tab.id === 'homework' && solveReady) {
        label += '<span class="lens-tab-dot" aria-label="solution found"></span>';
      }
      return '<button type="button" class="lens-tab' + (tab.id === active ? ' active' : '') + '" ' +
        'role="tab" aria-selected="' + (tab.id === active ? 'true' : 'false') + '" ' +
        'data-lens-tab="' + tab.id + '">' + label + '</button>';
    }).join('');

    return '' +
      '<div class="lens-result-head">' +
        '<p class="lens-result-kicker">Visual result</p>' +
        '<h2>' + (solveReady ? 'We found an answer.' : 'Here is what we read.') + '</h2>' +
      '</div>' +
      '<div class="lens-tabs" role="tablist" aria-label="Result type">' + tabHtml + '</div>' +
      '<div class="lens-result-body" id="lensResultBody">' + renderActiveBody() + '</div>';
  }

  function renderBody() {
    var body = document.getElementById('lensResultBody');
    if (!body || !resultState || resultState.kind !== 'ocr') return;
    body.innerHTML = renderActiveBody();
    var frame = resultEl.querySelector('.lens-tabs');
    if (frame) {
      frame.querySelectorAll('[data-lens-tab]').forEach(function (button) {
        var active = button.getAttribute('data-lens-tab') === resultState.active;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
      });
    }
  }

  function renderActiveBody() {
    if (!resultState) return '';
    if (resultState.active === 'search') return renderSearchTab();
    if (resultState.active === 'homework') return renderHomeworkTab();
    if (resultState.active === 'translate') return renderTranslateTab();
    return renderTextTab();
  }

  function renderTextTab() {
    var text = resultState.text || '';
    if (resultState.ocrStatus === 'loading') {
      return '<div class="lens-loading"><span class="lens-spinner"></span><p>Reading the photo…</p></div>';
    }
    return '' +
      '<div class="lens-text-block">' +
        '<pre class="lens-pre lens-pre-tall">' + escapeHtml(text) + '</pre>' +
        '<div class="lens-inline-actions">' +
          '<button type="button" class="lens-chip" data-lens-action="copy" data-value="' + escapeAttr(text) + '">Copy</button>' +
          '<button type="button" class="lens-chip" data-lens-action="listen" data-value="' + escapeAttr(text) + '">Listen</button>' +
          '<button type="button" class="lens-chip" data-lens-action="search" data-query="' + escapeAttr(text) + '">Search this text</button>' +
        '</div>' +
      '</div>' +
      '<div class="lens-result-actions">' +
        '<button type="button" class="lens-secondary" data-lens-action="new-scan">New scan</button>' +
      '</div>';
  }

  function renderSearchTab() {
    if (resultState.searchStatus === 'loading') {
      return '<div class="lens-loading"><span class="lens-spinner"></span><p>Looking up sources…</p></div>';
    }
    if (resultState.searchStatus === 'error') {
      return '' +
        '<p class="lens-error-text">' + escapeHtml(resultState.searchError) + '</p>' +
        '<div class="lens-result-actions"><button type="button" class="lens-primary" data-lens-action="search" data-query="' + escapeAttr(resultState.text) + '">Try again</button></div>';
    }
    if (resultState.searchStatus === 'idle') {
      return '' +
        '<p class="lens-copy">Search the text from this photo on 8search.</p>' +
        '<div class="lens-result-actions"><button type="button" class="lens-primary" data-lens-action="search" data-query="' + escapeAttr(resultState.text) + '">Search this text</button></div>';
    }

    var data = resultState.search || {};
    if (data.limit_reached) {
      return '' +
        '<div class="lens-answer"><p class="lens-answer-kicker">Search limit</p>' +
        '<p>You have used your free searches. <a href="login.html">Sign in</a> for unlimited searching.</p></div>';
    }

    var html = '';
    var answer = data.answer;
    if (answer) {
      html += '<div class="lens-answer">' +
        '<p class="lens-answer-kicker">Quick answer</p>' +
        '<h3>' + escapeHtml(answer.title || 'Answer') + '</h3>' +
        '<p>' + escapeHtml(answer.text || '') + '</p>' +
        (answer.source ? '<p class="lens-answer-source">' + escapeHtml(answer.source) + '</p>' : '') +
        '</div>';
    }

    var wiki = data.wikipedia;
    if (wiki) {
      html += '<div class="lens-answer">' +
        '<p class="lens-answer-kicker">Wikipedia</p>' +
        '<h3>' + escapeHtml(wiki.title || '') + '</h3>' +
        '<p>' + escapeHtml((wiki.extract || '').slice(0, 380)) + '</p>' +
        '<a class="lens-inline-link" href="' + escapeAttr(wiki.url || '#') + '" target="_blank" rel="noopener noreferrer">Read more</a>' +
        '</div>';
    }

    var results = data.results || [];
    if (results.length) {
      html += '<div class="lens-source-list"><p class="lens-answer-kicker">Sources</p>';
      results.slice(0, 4).forEach(function (result) {
        html += '<a class="lens-source" href="' + escapeAttr(result.url || '#') + '" target="_blank" rel="noopener noreferrer">' +
          '<strong>' + escapeHtml(result.title || result.url || 'Source') + '</strong>' +
          '<span>' + escapeHtml(result.snippet || '') + '</span>' +
          '</a>';
      });
      html += '</div>';
    }
    if (!html) html = '<p class="lens-copy">No matching text result was found.</p>';

    html += '<div class="lens-result-actions">' +
      '<button type="button" class="lens-primary" data-lens-action="full-search" data-query="' + escapeAttr(resultState.searchQuery || resultState.text) + '">See all results</button>' +
      '<button type="button" class="lens-secondary" data-lens-action="new-scan">New scan</button>' +
      '</div>';
    return html;
  }

  function renderHomeworkTab() {
    if (resultState.solveStatus === 'loading') {
      return '<div class="lens-loading"><span class="lens-spinner"></span><p>Solving the question…</p></div>';
    }
    if (resultState.solveStatus === 'error') {
      return '' +
        '<p class="lens-error-text">' + escapeHtml(resultState.solveError) + '</p>' +
        '<div class="lens-result-actions"><button type="button" class="lens-primary" data-lens-action="search" data-query="' + escapeAttr(resultState.text) + '">Ask 8search instead</button></div>';
    }

    var solve = resultState.solve || {};
    if (solve.solved) {
      var steps = (solve.steps || []).map(function (step) {
        return '<li>' + escapeHtml(step) + '</li>';
      }).join('');
      return '' +
        '<div class="lens-solution">' +
          '<p class="lens-answer-kicker">Homework solution</p>' +
          '<div class="lens-solution-main">' + escapeHtml(solve.solution || '') + '</div>' +
          (solve.normalized ? '<p class="lens-detected">Detected: <code>' + escapeHtml(solve.normalized) + '</code></p>' : '') +
          (steps ? '<div class="lens-steps"><p class="lens-answer-kicker">Steps</p><ol>' + steps + '</ol></div>' : '') +
        '</div>' +
        '<div class="lens-result-actions">' +
          '<button type="button" class="lens-primary" data-lens-action="copy" data-value="' + escapeAttr(solve.solution || '') + '">Copy answer</button>' +
          '<button type="button" class="lens-secondary" data-lens-action="search" data-query="' + escapeAttr(resultState.text) + '">Search this question</button>' +
        '</div>';
    }

    return '' +
      '<p class="lens-copy">No equation was detected in this photo. Ask 8search the question instead — we will look for a direct answer.</p>' +
      '<div class="lens-result-actions">' +
        '<button type="button" class="lens-primary" data-lens-action="search" data-query="' + escapeAttr(resultState.text) + '">Ask 8search</button>' +
        '<button type="button" class="lens-secondary" data-lens-action="new-scan">New scan</button>' +
      '</div>';
  }

  function renderTranslateTab() {
    var target = resultState.translateTarget || 'en';
    var options = LANGUAGES.map(function (pair) {
      return '<option value="' + escapeAttr(pair[0]) + '"' + (pair[0] === target ? ' selected' : '') + '>' + escapeHtml(pair[1]) + '</option>';
    }).join('');

    var html = '' +
      '<div class="lens-translate-row">' +
        '<label for="lensTargetLang">Translate to</label>' +
        '<select id="lensTargetLang" class="lens-select">' + options + '</select>' +
        '<button type="button" class="lens-primary lens-translate-go" data-lens-action="translate">Translate</button>' +
      '</div>';

    if (resultState.translateStatus === 'loading') {
      html += '<div class="lens-loading"><span class="lens-spinner"></span><p>Translating…</p></div>';
    } else if (resultState.translateStatus === 'error') {
      html += '<p class="lens-error-text">' + escapeHtml(resultState.translateError) + '</p>';
    } else if (resultState.translation) {
      html += '<div class="lens-translation">' +
        '<p class="lens-answer-kicker">' + escapeHtml((resultState.translation.source_language || 'auto').toUpperCase()) +
        ' → ' + escapeHtml((resultState.translation.target_language || target).toUpperCase()) + '</p>' +
        '<pre class="lens-pre">' + escapeHtml(resultState.translation.text || '') + '</pre>' +
        '<div class="lens-inline-actions">' +
          '<button type="button" class="lens-chip" data-lens-action="copy" data-value="' + escapeAttr(resultState.translation.text || '') + '">Copy</button>' +
          '<button type="button" class="lens-chip" data-lens-action="listen" data-value="' + escapeAttr(resultState.translation.text || '') + '">Listen</button>' +
        '</div>' +
      '</div>';
    } else {
      html += '<p class="lens-copy">Choose a language and translate the text from this photo.</p>' +
        '<div class="lens-text-block"><pre class="lens-pre">' + escapeHtml(resultState.text || '') + '</pre></div>';
    }
    return html;
  }

  // ---------- Panel actions ----------
  function setActiveTab(tab) {
    if (!resultState || resultState.kind !== 'ocr') return;
    resultState.active = tab;
    userChangedTab = true;
    renderBody();
    if (tab === 'search' && resultState.searchStatus === 'idle') {
      loadSearch(resultState.text, true);
    }
    if (tab === 'translate' && resultState.translateStatus === 'done' && !resultState.translation) {
      renderBody();
    }
  }

  async function copyText(value) {
    var text = String(value || '');
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast('Copied to clipboard');
    } catch (e) {
      var area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try { document.execCommand('copy'); showToast('Copied to clipboard'); }
      catch (err) { showToast('Could not copy on this browser.'); }
      area.remove();
    }
  }

  function listenTo(value) {
    if (!window.speechSynthesis) {
      showToast('Speech is not available on this browser.');
      return;
    }
    try {
      window.speechSynthesis.cancel();
      var utterance = new SpeechSynthesisUtterance(String(value || '').slice(0, 4000));
      utterance.lang = 'en-US';
      utterance.rate = 0.98;
      window.speechSynthesis.speak(utterance);
      showToast('Reading aloud');
    } catch (e) {
      showToast('Speech is not available on this browser.');
    }
  }

  function performFullSearch(query) {
    var input = document.getElementById('searchInput');
    var form = document.getElementById('searchForm');
    if (!input || !form) return;
    closeLens();
    input.value = query;
    form.requestSubmit();
  }

  function newScan() {
    resetResult();
    userChangedTab = false;
    startCamera();
  }

  // ---------- File upload ----------
  function chooseFile() {
    if (fileInput) fileInput.click();
  }

  async function handleFile(file) {
    if (!file) return;
    if (!/^image\//.test(file.type)) {
      showToast('Choose an image file.');
      return;
    }
    stopCamera();
    stopScanLoop();
    resetCaptureView();
    busy = true;
    setStatus('Loading photo…');
    setProgress(null);
    var url = URL.createObjectURL(file);
    var image = new Image();
    image.onload = async function () {
      URL.revokeObjectURL(url);
      if (!drawToCanvas(image, 1800)) {
        busy = false;
        showToast('That image could not be opened.');
        return;
      }
      showCapturedFrame(canvas.toDataURL('image/jpeg', 0.92));
      setStatus('Reading the photo…');
      await processCanvas(canvas);
    };
    image.onerror = function () {
      URL.revokeObjectURL(url);
      busy = false;
      showToast('That image could not be opened.');
    };
    image.src = url;
  }

  // ---------- Open / close ----------
  function openLens() {
    if (opened) return;
    opened = true;
    userChangedTab = false;
    modal.classList.remove('hidden');
    document.body.classList.add('lens-open');
    resetResult();
    startCamera();
    window.setTimeout(function () {
      if (closeBtn) closeBtn.focus();
    }, 40);
  }

  function closeLens() {
    opened = false;
    stopCamera();
    window.speechSynthesis && window.speechSynthesis.cancel();
    modal.classList.add('hidden');
    document.body.classList.remove('lens-open');
    resetResult();
  }

  // ---------- Wiring ----------
  var trigger = document.getElementById('cameraSearchBtn');
  if (trigger) trigger.addEventListener('click', openLens);
  if (closeBtn) closeBtn.addEventListener('click', closeLens);
  if (backdrop) backdrop.addEventListener('click', closeLens);
  if (shutterBtn) shutterBtn.addEventListener('click', capturePhoto);
  if (switchBtn) switchBtn.addEventListener('click', switchCamera);
  if (torchBtn) torchBtn.addEventListener('click', toggleTorch);
  if (uploadBtn) uploadBtn.addEventListener('click', chooseFile);
  if (uploadTopBtn) uploadTopBtn.addEventListener('click', chooseFile);
  if (errorUploadBtn) errorUploadBtn.addEventListener('click', chooseFile);
  if (retakeBtn) retakeBtn.addEventListener('click', newScan);
  if (newScanBtn) newScanBtn.addEventListener('click', newScan);
  if (typeBtn) typeBtn.addEventListener('click', function () {
    closeLens();
    var input = document.getElementById('searchInput');
    if (input) input.focus();
  });
  if (fileInput) fileInput.addEventListener('change', function () {
    if (fileInput.files && fileInput.files[0]) handleFile(fileInput.files[0]);
    fileInput.value = '';
  });

  if (resultEl) {
    resultEl.addEventListener('click', function (event) {
      var tab = event.target.closest('[data-lens-tab]');
      if (tab) {
        setActiveTab(tab.getAttribute('data-lens-tab'));
        return;
      }
      var actionEl = event.target.closest('[data-lens-action]');
      if (!actionEl) return;
      var action = actionEl.getAttribute('data-lens-action');
      if (action === 'copy') copyText(actionEl.getAttribute('data-value') || '');
      if (action === 'listen') listenTo(actionEl.getAttribute('data-value') || '');
      if (action === 'search') {
        resultState.active = 'search';
        userChangedTab = true;
        renderResult();
        loadSearch(actionEl.getAttribute('data-query') || resultState.text, true);
      }
      if (action === 'full-search') {
        performFullSearch(actionEl.getAttribute('data-query') || resultState.text);
      }
      if (action === 'translate') {
        var select = document.getElementById('lensTargetLang');
        translateText(resultState.text, select ? select.value : 'en');
      }
      if (action === 'new-scan') newScan();
    });
  }

  document.addEventListener('keydown', function (event) {
    if (!opened) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closeLens();
    }
  });

  // Expose a small API for testing and future integrations.
  window.EightSearchLens = {
    open: openLens,
    close: closeLens,
    startScan: function () { startCamera(); }
  };
})();
