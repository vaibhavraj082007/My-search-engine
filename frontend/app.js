/* =========================================================
   8search – Core Application Logic (app.js)
   ========================================================= */

(function () {
  'use strict';

  // ---------- DOM refs ----------
  var searchForm      = document.getElementById('searchForm');
  var searchInput     = document.getElementById('searchInput');
  var searchSection   = document.getElementById('searchSection');
  var resultsSection  = document.getElementById('resultsSection');
  var resultsContainer= document.getElementById('resultsContainer');
  var pagination      = document.getElementById('pagination');
  var userArea        = document.getElementById('userArea');
  var loginBanner     = document.getElementById('loginBanner');
  var bannerDismiss   = document.getElementById('bannerDismiss');
  var luckyBtn        = document.getElementById('luckyBtn');
  var utcClock        = document.getElementById('utcClock');
  var globeSection    = document.querySelector('.globe-section');
  var signinPrompt    = document.getElementById('signinPrompt');
  var signinBackdrop  = document.getElementById('signinBackdrop');
  var signinClose     = document.getElementById('signinClose');
  var signinContinue  = document.getElementById('signinContinue');
  var feedbackForm    = document.getElementById('feedbackForm');
  var feedbackName    = document.getElementById('feedbackName');
  var feedbackEmail   = document.getElementById('feedbackEmail');
  var feedbackMessage = document.getElementById('feedbackMessage');
  var feedbackSubmit  = document.getElementById('feedbackSubmit');
  var feedbackStatus  = document.getElementById('feedbackStatus');
  var searchTabs      = document.querySelectorAll('.search-tab');
  var addShortcutBtn  = document.getElementById('addShortcutBtn');
  var shortcutRow     = document.getElementById('shortcutRow');
  var closeGlobeBtn   = document.getElementById('closeGlobeBtn');
  var infoDialog      = document.getElementById('infoDialog');
  var infoTitle       = document.getElementById('infoTitle');
  var infoBody        = document.getElementById('infoBody');
  var infoClose       = document.getElementById('infoClose');
  var suggestionsEl   = document.getElementById('suggestions');
  var engineBanner    = document.getElementById('engineBanner');
  var engineBannerClose = document.getElementById('engineBannerClose');
  var trendingNews    = document.getElementById('trendingNews');

  var currentUser  = null;
  var currentQuery = '';
  var currentPage  = 1;
  var currentMode  = 'web';
  var searchSeq    = 0;
  var PAGE_WINDOW  = 5;
  var MAX_PAGE     = 10;
  var signinShown  = false;
  var MODES        = ['web', 'ai', 'images', 'code'];
  var MAX_QUERY    = 500;
  var ENGINE_HINT_KEY = '8search.engineHintDismissed';

  var MODE_PLACEHOLDERS = {
    web:      'Search anything or type a calculation…',
    ai:       'Ask a question and get a direct answer…',
    images:   'Search for images…',
    code:     'Search code, repos, and documentation…'
  };

  // ---------- UTC Clock ----------
  function updateUTCClock() {
    var now = new Date();
    var h = String(now.getUTCHours()).padStart(2, '0');
    var m = String(now.getUTCMinutes()).padStart(2, '0');
    var s = String(now.getUTCSeconds()).padStart(2, '0');
    utcClock.textContent = 'UTC ' + h + ':' + m + ':' + s;
  }
  updateUTCClock();
  setInterval(updateUTCClock, 1000);

  // ---------- Sign-in prompt ----------
  function showSigninPrompt() {
    if (!signinPrompt || currentUser || signinShown) return;
    if (document.body.classList.contains('lens-open')) {
      window.setTimeout(showSigninPrompt, 8000);
      return;
    }
    signinShown = true;
    signinPrompt.classList.remove('hidden');
    document.body.classList.add('signin-open');
    window.setTimeout(function () {
      // Don't steal focus if the visitor already started typing.
      if (signinContinue && document.activeElement === document.body) {
        signinContinue.focus();
      }
    }, 60);
  }

  function hideSigninPrompt() {
    if (!signinPrompt) return;
    signinPrompt.classList.add('hidden');
    document.body.classList.remove('signin-open');
    if (searchInput) searchInput.focus();
  }

  if (signinClose) signinClose.addEventListener('click', hideSigninPrompt);
  if (signinBackdrop) signinBackdrop.addEventListener('click', hideSigninPrompt);

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' || !signinPrompt) return;
    if (!signinPrompt.classList.contains('hidden')) hideSigninPrompt();
  });

  // ---------- Auth ----------
  function checkAuth() {
    fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) {
        currentUser = d.email;
        if (feedbackEmail && !feedbackEmail.value) feedbackEmail.value = currentUser;
        renderUserArea();
      })
      .catch(function () {
        currentUser = null;
        renderUserArea();
        // Opening the site as a guest mirrors the usual sign-in prompt:
        // show it once, shortly after the page settles.
        window.setTimeout(showSigninPrompt, 1600);
      });
  }

  function renderUserArea() {
    if (currentUser) {
      userArea.innerHTML =
        '<div class="user-info">' +
          '<span class="user-email">' + esc(currentUser) + '</span>' +
          '<button class="logout-btn" id="logoutBtn">Sign out</button>' +
        '</div>';
      document.getElementById('logoutBtn').addEventListener('click', handleLogout);
    } else {
      userArea.innerHTML = '<a href="login.html" class="sign-in-link">Sign in</a>';
    }
  }

  function handleLogout() {
    fetch('/api/logout', { method: 'POST', credentials: 'same-origin' })
      .finally(function () { currentUser = null; renderUserArea(); goHome(); });
  }

  // ---------- Search modes ----------
  function setMode(mode, options) {
    if (MODES.indexOf(mode) === -1) mode = 'web';
    currentMode = mode;

    searchTabs.forEach(function (tab) {
      var active = tab.getAttribute('data-mode') === mode;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.setAttribute('tabindex', active ? '0' : '-1');
    });

    if (searchInput) {
      searchInput.placeholder = MODE_PLACEHOLDERS[mode] || MODE_PLACEHOLDERS.web;
    }

    var opts = options || {};
    if (opts.rerun && currentQuery) {
      performSearch(currentQuery, 1, false, 'push');
    }
  }

  searchTabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      var mode = tab.getAttribute('data-mode') || 'web';
      if (mode === currentMode) return;
      setMode(mode, { rerun: true });
    });

    tab.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      var index = MODES.indexOf(tab.getAttribute('data-mode'));
      var next = e.key === 'ArrowRight'
        ? (index + 1) % MODES.length
        : (index - 1 + MODES.length) % MODES.length;
      searchTabs[next].focus();
      setMode(MODES[next], { rerun: true });
    });
  });

  // ---------- Home ----------
  function goHome(pushHistory) {
    document.body.classList.remove('searching');
    searchSection.classList.remove('compact');
    resultsSection.classList.add('hidden');
    resultsContainer.innerHTML = '';
    pagination.innerHTML = '';
    if (globeSection) globeSection.classList.add('hidden');
    if (trendingNews) trendingNews.classList.remove('hidden');
    closeSuggestions();
    searchInput.value = '';
    currentQuery = '';
    currentPage  = 1;
    searchSeq    = 0;
    setMode('web');

    if (pushHistory !== false) {
      try { window.history.pushState({}, '', '/'); } catch (e) {}
    }
    if (window.EightSearchNews && window.EightSearchNews.load) {
      window.EightSearchNews.load();
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  var logo = document.querySelector('.top-bar-logo');
  if (logo) logo.addEventListener('click', function (e) { e.preventDefault(); goHome(); });

  // ---------- Search submit ----------
  searchForm.addEventListener('submit', function (e) {
    e.preventDefault();
    closeSuggestions();
    doSearch(searchInput.value.trim());
  });

  var searchIcon = document.querySelector('.search-icon');
  if (searchIcon) {
    searchIcon.style.cursor = 'pointer';
    searchIcon.addEventListener('click', function () {
      doSearch(searchInput.value.trim());
    });
  }

  if (luckyBtn) luckyBtn.addEventListener('click', function () {
    doSearch(searchInput.value.trim(), true);
  });

  // ---------- Live suggestions ----------
  var suggestState = {
    timer: null,
    controller: null,
    items: [],
    active: -1,
    seq: 0,
    lastQuery: ''
  };

  function closeSuggestions() {
    if (!suggestionsEl) return;
    if (suggestState.timer) {
      window.clearTimeout(suggestState.timer);
      suggestState.timer = null;
    }
    if (suggestState.controller) {
      try { suggestState.controller.abort(); } catch (e) {}
      suggestState.controller = null;
    }
    suggestState.items = [];
    suggestState.active = -1;
    suggestState.seq += 1;
    suggestionsEl.classList.add('hidden');
    suggestionsEl.replaceChildren();
    searchInput.setAttribute('aria-expanded', 'false');
    searchInput.removeAttribute('aria-activedescendant');
  }

  function updateSuggestionActive(nextIndex) {
    if (!suggestState.items.length) return;
    suggestState.active = (nextIndex + suggestState.items.length) % suggestState.items.length;
    var options = suggestionsEl.querySelectorAll('.suggestion-item');
    options.forEach(function (option, index) {
      var active = index === suggestState.active;
      option.classList.toggle('active', active);
      option.setAttribute('aria-selected', active ? 'true' : 'false');
      if (active) {
        searchInput.setAttribute('aria-activedescendant', option.id);
        if (option.scrollIntoView) option.scrollIntoView({ block: 'nearest' });
      }
    });
    if (suggestState.active < 0) searchInput.removeAttribute('aria-activedescendant');
  }

  function chooseSuggestion(text) {
    if (!text) return;
    searchInput.value = text;
    closeSuggestions();
    doSearch(text);
  }

  function renderSuggestions(items, typed) {
    if (!suggestionsEl) return;
    suggestState.items = items.slice(0, 8);
    suggestState.active = -1;
    suggestionsEl.replaceChildren();
    if (!suggestState.items.length) {
      suggestionsEl.classList.add('hidden');
      searchInput.setAttribute('aria-expanded', 'false');
      return;
    }

    suggestState.items.forEach(function (entry, index) {
      var text = typeof entry === 'string' ? entry : entry.text;
      if (!text) return;
      var kind = typeof entry === 'string' ? 'web' : (entry.kind || 'web');
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'suggestion-item';
      button.id = 'suggestion-' + index;
      button.setAttribute('role', 'option');
      button.setAttribute('aria-selected', 'false');

      var icon = document.createElement('span');
      icon.className = 'suggestion-icon suggestion-icon-' + kind;
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = kind === 'popular' ? '↗' : (kind === 'local' ? '⌕' : 'W');

      var label = document.createElement('span');
      label.className = 'suggestion-text';
      label.textContent = text;

      var hint = document.createElement('span');
      hint.className = 'suggestion-kind';
      hint.textContent = kind === 'popular' ? 'Popular' : (kind === 'local' ? 'On this site' : '');

      button.appendChild(icon);
      button.appendChild(label);
      if (hint.textContent) button.appendChild(hint);
      // pointerdown prevents the input blur before click.
      button.addEventListener('pointerdown', function (e) { e.preventDefault(); });
      button.addEventListener('click', function () { chooseSuggestion(text); });
      button.addEventListener('mouseenter', function () { updateSuggestionActive(index); });
      suggestionsEl.appendChild(button);
    });

    suggestionsEl.classList.remove('hidden');
    searchInput.setAttribute('aria-expanded', 'true');
  }

  function requestSuggestions(typed) {
    var query = (typed || '').trim();
    if (!query) { closeSuggestions(); return; }
    if (query === suggestState.lastQuery && suggestState.items.length) return;
    suggestState.lastQuery = query;
    var seq = ++suggestState.seq;
    if (suggestState.controller) {
      try { suggestState.controller.abort(); } catch (e) {}
    }
    var controller = window.AbortController ? new AbortController() : null;
    suggestState.controller = controller;

    fetch('/api/suggest?q=' + encodeURIComponent(query) + '&format=rich',
          { credentials: 'same-origin', signal: controller ? controller.signal : undefined })
      .then(function (r) {
        if (!r.ok) throw new Error('suggestions unavailable');
        return r.json();
      })
      .then(function (data) {
        if (seq !== suggestState.seq) return;
        if (!searchInput.value.trim() || searchInput.value.trim() !== query) return;
        var items = data && Array.isArray(data.suggestions) ? data.suggestions : [];
        renderSuggestions(items, query);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (seq === suggestState.seq) {
          suggestionsEl.classList.add('hidden');
          searchInput.setAttribute('aria-expanded', 'false');
        }
      });
  }

  function scheduleSuggestions() {
    var query = searchInput.value.trim();
    if (!query) { closeSuggestions(); return; }
    if (suggestState.timer) window.clearTimeout(suggestState.timer);
    suggestState.timer = window.setTimeout(function () {
      suggestState.timer = null;
      requestSuggestions(query);
    }, 120);
  }

  searchInput.addEventListener('input', scheduleSuggestions);
  searchInput.addEventListener('focus', scheduleSuggestions);
  searchInput.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (!suggestionsEl.classList.contains('hidden')) {
        e.preventDefault();
        closeSuggestions();
      }
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (suggestionsEl.classList.contains('hidden') || !suggestState.items.length) return;
      e.preventDefault();
      updateSuggestionActive(suggestState.active + (e.key === 'ArrowDown' ? 1 : -1));
      return;
    }
    if (e.key === 'Enter' && suggestState.active >= 0 && suggestState.items.length) {
      var active = suggestState.items[suggestState.active];
      var value = typeof active === 'string' ? active : active.text;
      if (value) {
        e.preventDefault();
        chooseSuggestion(value);
      }
    }
  });

  document.addEventListener('click', function (e) {
    if (!suggestionsEl || suggestionsEl.classList.contains('hidden')) return;
    if (searchForm.contains(e.target)) return;
    closeSuggestions();
  });

  // ---------- Landing category pills ----------
  var landingPills = document.querySelectorAll('.landing-pill');
  landingPills.forEach(function (pill) {
    pill.addEventListener('click', function () {
      var q = pill.getAttribute('data-query') || pill.textContent.trim();
      searchInput.value = q;
      doSearch(q);
    });
  });

  // ---------- Voice search (mic button) ----------
  var micBtn = document.getElementById('voiceSearchBtn');
  if (micBtn) {
    var SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRec) {
      var recognition = new SpeechRec();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onstart = function () {
        micBtn.classList.add('listening');
        searchInput.placeholder = 'Listening… speak now';
      };
      recognition.onresult = function (event) {
        var transcript = event.results && event.results[0] && event.results[0][0] ? event.results[0][0].transcript : '';
        if (transcript) {
          searchInput.value = transcript;
          doSearch(transcript);
        }
      };
      recognition.onerror = function () {
        micBtn.classList.remove('listening');
        searchInput.placeholder = MODE_PLACEHOLDERS[currentMode] || MODE_PLACEHOLDERS.web;
      };
      recognition.onend = function () {
        micBtn.classList.remove('listening');
        searchInput.placeholder = MODE_PLACEHOLDERS[currentMode] || MODE_PLACEHOLDERS.web;
      };

      micBtn.addEventListener('click', function () {
        try {
          recognition.start();
        } catch (err) {
          try { recognition.stop(); } catch (e) {}
        }
      });
    } else {
      micBtn.addEventListener('click', function () {
        searchInput.focus();
      });
    }
  }

  // ---------- Camera / visual search ----------
  // Handled by lens.js so the camera opens in-app instead of a new tab.

  // ---------- Slash-to-search ----------
  document.addEventListener('keydown', function (e) {
    if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
    var el = document.activeElement;
    var tag = el && el.tagName ? el.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || (el && el.isContentEditable)) return;
    e.preventDefault();
    searchInput.focus();
    searchInput.select();
  });

  // ---------- Shortcut apps ----------
  function shortcutQuery() {
    return (searchInput.value || currentQuery || '').trim();
  }

  function openExternal(url) {
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  document.querySelectorAll('.shortcut[data-shortcut]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var kind = btn.getAttribute('data-shortcut');
      var q = shortcutQuery();

      if (kind === 'youtube') {
        openExternal(q
          ? 'https://www.youtube.com/results?search_query=' + encodeURIComponent(q)
          : 'https://www.youtube.com/');
        return;
      }

      if (kind === 'github') {
        openExternal(q
          ? 'https://github.com/search?q=' + encodeURIComponent(q) + '&type=repositories'
          : 'https://github.com/');
        return;
      }

      if (kind === 'wikipedia') {
        openExternal(q
          ? 'https://en.wikipedia.org/w/index.php?search=' + encodeURIComponent(q)
          : 'https://en.wikipedia.org/');
        return;
      }

      if (kind === 'news') {
        var newsQuery = q ? q + ' news' : 'latest news';
        setMode('web', { rerun: false });
        searchInput.value = newsQuery;
        doSearch(newsQuery);
        return;
      }

      if (kind === 'maps') {
        if (window.EightSearchMap && window.EightSearchMap.revealMap) {
          window.EightSearchMap.revealMap();
        }
        return;
      }

      if (kind === 'weather') {
        if (!navigator.geolocation || !window.EightSearchMap) {
          if (window.EightSearchMap && window.EightSearchMap.revealMap) {
            window.EightSearchMap.revealMap();
          }
          return;
        }
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            window.EightSearchMap.openWeatherAt(pos.coords.latitude, pos.coords.longitude);
          },
          function () {
            if (window.EightSearchMap.revealMap) window.EightSearchMap.revealMap();
          },
          { timeout: 8000, maximumAge: 300000 }
        );
      }
    });
  });

  // ---------- Custom shortcuts ----------
  var SHORTCUT_KEY = '8search.shortcuts';

  function readCustomShortcuts() {
    try {
      var parsed = JSON.parse(window.localStorage.getItem(SHORTCUT_KEY) || '[]');
      return Array.isArray(parsed) ? parsed.filter(function (s) {
        return s && s.url && s.label;
      }) : [];
    } catch (e) {
      return [];
    }
  }

  function saveCustomShortcuts(list) {
    try { window.localStorage.setItem(SHORTCUT_KEY, JSON.stringify(list)); } catch (e) {}
  }

  function renderCustomShortcuts() {
    if (!shortcutRow || !addShortcutBtn) return;
    shortcutRow.querySelectorAll('.shortcut-custom').forEach(function (el) { el.remove(); });

    readCustomShortcuts().forEach(function (entry) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'shortcut shortcut-custom';
      btn.setAttribute('aria-label', 'Open ' + entry.label);

      var icon = document.createElement('span');
      icon.className = 'shortcut-icon shortcut-icon-custom';
      var letter = document.createElement('span');
      letter.textContent = entry.label.charAt(0).toUpperCase();
      icon.appendChild(letter);

      var label = document.createElement('span');
      label.className = 'shortcut-label';
      label.textContent = entry.label;

      btn.appendChild(icon);
      btn.appendChild(label);
      btn.addEventListener('click', function () { openExternal(entry.url); });
      shortcutRow.insertBefore(btn, addShortcutBtn);
    });
  }

  if (addShortcutBtn) {
    addShortcutBtn.addEventListener('click', function () {
      var raw = window.prompt('Paste a website URL to add it as a shortcut:');
      if (raw === null) return;
      raw = raw.trim();
      if (!raw) return;

      var url;
      try {
        url = new URL(/^https?:\/\//i.test(raw) ? raw : 'https://' + raw);
        if (!/^https?:$/.test(url.protocol)) throw new Error('bad protocol');
      } catch (e) {
        window.alert('That does not look like a valid website URL.');
        return;
      }

      var label = url.hostname.replace(/^www\./, '').split('.')[0] || 'Shortcut';
      label = label.charAt(0).toUpperCase() + label.slice(1);

      var list = readCustomShortcuts();
      list.push({ label: label, url: url.href });
      saveCustomShortcuts(list);
      renderCustomShortcuts();
    });
  }

  // ---------- Footer information dialog ----------
  var INFO_CONTENT = {
    privacy: {
      title: 'Privacy',
      body: '<p>8search keeps your account email and a securely hashed password so you can sign in. Guest searches use a short-lived cookie to apply the free-search limit.</p>' +
            '<p>Click-popularity data is stored with salted hashes of the IP address and browser identifier, never raw IP addresses or a readable click history. We do not sell your data or run advertising trackers.</p>' +
            '<p>Feedback you send is stored locally and emailed to the site owner so it can be read and answered.</p>'
    },
    ranking: {
      title: 'How ranking works',
      body: '<p>When people click a result on 8search, we remember that it was useful for that query. Results with more clicks move up; results nobody clicks move below them.</p>' +
            '<p>Clicks lower on the page count for more, because top results get clicked more by accident. Clicks fade with a 30-day half-life, and one lucky click cannot outrank a result with many clicks.</p>' +
            '<p>Only results 8search actually showed can be clicked, and we store just salted hashes of IP addresses and session identifiers. Brand-new queries keep the search provider order until there is data.</p>'
    },
    terms: {
      title: 'Terms',
      body: '<p>Use 8search lawfully and responsibly. Search results, images, news, and maps come from third-party sources and may change or be unavailable at any time.</p>' +
            '<p>Accounts are personal. Do not use the service to break the law, attack the site, or scrape it at a rate that harms other users. The service is provided as is, without warranties.</p>'
    },
    about: {
      title: 'About 8search',
      body: '<p>8search is an answer-first search engine: quick answers, a Wikipedia card, videos, news, and a live globe, all in one place.</p>' +
            '<p>It is a small independent project built with FastAPI, vanilla JavaScript, Leaflet, and open data sources. The light interface is designed to stay out of the way of the answer.</p>'
    }
  };

  function openInfo(key) {
    var info = INFO_CONTENT[key];
    if (!info || !infoDialog) return;
    infoTitle.textContent = info.title;
    infoBody.innerHTML = info.body;
    if (typeof infoDialog.showModal === 'function') infoDialog.showModal();
    else infoDialog.setAttribute('open', '');
  }

  document.querySelectorAll('.footer-link').forEach(function (link) {
    link.addEventListener('click', function () {
      openInfo(link.getAttribute('data-info'));
    });
  });

  if (infoClose) infoClose.addEventListener('click', function () { infoDialog.close(); });
  if (infoDialog) {
    infoDialog.addEventListener('click', function (e) {
      if (e.target === infoDialog) infoDialog.close();
    });
  }

  // ---------- Close map ----------
  if (closeGlobeBtn) {
    closeGlobeBtn.addEventListener('click', function () {
      if (globeSection) globeSection.classList.add('hidden');
    });
  }

  // ---------- URL / history ----------
  function readRoute() {
    try {
      var params = new URLSearchParams(window.location.search);
      var q = (params.get('q') || '').trim();
      var page = parseInt(params.get('page') || '1', 10);
      var mode = params.get('mode') || 'web';
      if (MODES.indexOf(mode) === -1) mode = 'web';
      if (!isFinite(page) || page < 1) page = 1;
      if (page > MAX_PAGE) page = MAX_PAGE;
      return { q: q, page: page, mode: mode };
    } catch (e) {
      return { q: '', page: 1, mode: 'web' };
    }
  }

  function updateUrl(query, page, historyMode, searchMode) {
    try {
      var params = new URLSearchParams();
      params.set('q', query);
      if (page > 1) params.set('page', String(page));
      if (searchMode && searchMode !== 'web') params.set('mode', searchMode);
      var url = window.location.pathname + '?' + params.toString();
      var state = { q: query, page: page, mode: searchMode || 'web' };
      if (historyMode === 'push') window.history.pushState(state, '', url);
      else window.history.replaceState(state, '', url);
    } catch (e) {}
  }

  // ---------- Repeat-search cache ----------
  // Repeating a query (back/forward, tab switch, resubmit) renders instantly
  // from this tab instead of waiting on the network. The server also caches,
  // but skipping the round-trip makes repeats feel immediate even on 5G.
  var SEARCH_CACHE_PREFIX = '8search.cache.';
  var SEARCH_CACHE_TTL = 5 * 60 * 1000;
  var SEARCH_CACHE_MAX = 40;

  function searchCacheKey(mode, query, page) {
    return SEARCH_CACHE_PREFIX + mode + '|' + page + '|' + query.trim().toLowerCase();
  }

  function readSearchCache(key) {
    try {
      var raw = window.sessionStorage.getItem(key);
      if (!raw) return null;
      var entry = JSON.parse(raw);
      if (!entry || !entry.at || Date.now() - entry.at > SEARCH_CACHE_TTL) {
        window.sessionStorage.removeItem(key);
        return null;
      }
      return entry.data || null;
    } catch (e) {
      return null;
    }
  }

  function writeSearchCache(key, data) {
    if (!data || data.redirect || data.limit_reached) return;
    try {
      var entries = [];
      for (var i = 0; i < window.sessionStorage.length; i++) {
        var name = window.sessionStorage.key(i);
        if (name && name.indexOf(SEARCH_CACHE_PREFIX) === 0) {
          var at = 0;
          try { at = JSON.parse(window.sessionStorage.getItem(name)).at || 0; } catch (e) {}
          entries.push({ name: name, at: at });
        }
      }
      entries.sort(function (a, b) { return a.at - b.at; });
      while (entries.length >= SEARCH_CACHE_MAX) {
        window.sessionStorage.removeItem(entries.shift().name);
      }
      window.sessionStorage.setItem(
        key,
        JSON.stringify({ at: Date.now(), data: data })
      );
    } catch (e) {
      // Private mode or a full quota: caching is optional.
    }
  }

  // A click can change the server-side order immediately. Drop this query
  // from the browser cache so the next search fetches the re-ranked page.
  function invalidateSearchCacheFor(query) {
    var suffix = '|' + String(query || '').trim().toLowerCase();
    try {
      for (var i = window.sessionStorage.length - 1; i >= 0; i--) {
        var name = window.sessionStorage.key(i);
        if (!name || name.indexOf(SEARCH_CACHE_PREFIX) !== 0) continue;
        if (name.slice(name.lastIndexOf('|')).toLowerCase() === suffix) {
          window.sessionStorage.removeItem(name);
        }
      }
    } catch (e) {}
  }

  // ---------- Click-popularity tracking ----------
  function clickAttrs(kind, url, title, position, token) {
    if (!url || !token) return '';
    var pos = parseInt(position, 10);
    if (!isFinite(pos) || pos < 0) pos = 0;
    return ' data-click-kind="' + escAttr(kind) + '"' +
           ' data-click-url="' + escAttr(url) + '"' +
           ' data-click-title="' + escAttr(title || '') + '"' +
           ' data-click-position="' + pos + '"' +
           ' data-click-token="' + escAttr(token) + '"';
  }

  function trackResultClick(link) {
    if (!link) return;
    var kind  = link.getAttribute('data-click-kind');
    var token = link.getAttribute('data-click-token');
    var url   = link.getAttribute('data-click-url') || link.href;
    if (!kind || !url) return;
    if (!token) {
      // A payload cached before ranking shipped has no token. Drop it so the
      // next search asks the server for a fresh, trackable response.
      invalidateSearchCacheFor(currentQuery);
      return;
    }

    var position = parseInt(link.getAttribute('data-click-position') || '0', 10);
    var payload = JSON.stringify({
      query: currentQuery,
      url: url,
      title: link.getAttribute('data-click-title') || '',
      position: isFinite(position) ? position : 0,
      kind: kind,
      token: token
    });

    // sendBeacon is queued by the browser before navigation and never blocks
    // the link opening. fetch(keepalive) is the fallback for older browsers.
    var sent = false;
    try {
      if (navigator.sendBeacon) {
        sent = navigator.sendBeacon(
          '/api/click',
          new Blob([payload], { type: 'application/json' })
        );
      }
    } catch (e) { sent = false; }

    if (!sent) {
      try {
        fetch('/api/click', {
          method: 'POST',
          credentials: 'same-origin',
          keepalive: true,
          headers: { 'Content-Type': 'application/json' },
          body: payload
        });
      } catch (e) {}
    }

    invalidateSearchCacheFor(currentQuery);
  }

  function clickTarget(node) {
    while (node && node !== resultsContainer) {
      if (node.getAttribute && node.getAttribute('data-click-kind')) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  // Capture phase so the beacon is queued before the browser follows the
  // link. Ctrl/Cmd+click and ordinary clicks both fire "click"; middle-click
  // opens a new tab and fires "auxclick" instead.
  resultsContainer.addEventListener('click', function (e) {
    var link = clickTarget(e.target);
    if (link) trackResultClick(link);
  }, true);
  resultsContainer.addEventListener('auxclick', function (e) {
    if (e.button !== 1) return;
    var link = clickTarget(e.target);
    if (link) trackResultClick(link);
  }, true);

  function doSearch(q, lucky) {
    if (!q) return;
    // URL-like → navigate
    if (q.indexOf('.') !== -1 && q.indexOf(' ') === -1) {
      window.location.href = /^https?:\/\//i.test(q) ? q : 'https://' + q;
      return;
    }
    performSearch(q, 1, lucky, 'push');
  }

  // ---------- Search ----------
  function performSearch(query, page, lucky, historyMode) {
    if (currentMode === 'images' && !lucky) {
      performImageSearch(query, page, historyMode);
      return;
    }

    currentQuery = query;
    currentPage  = page;
    var seq = ++searchSeq;

    // Switch to results layout
    document.body.classList.add('searching');
    searchSection.classList.add('compact');
    if (globeSection) globeSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');

    var cacheKey = searchCacheKey(currentMode, query, page);
    if (!lucky) {
      var cached = readSearchCache(cacheKey);
      if (cached) {
        currentPage = cached.page || page;
        if (historyMode) updateUrl(query, currentPage, historyMode, currentMode);
        renderResults(cached);
        pagination.setAttribute('aria-busy', 'false');
        return;
      }
    }

    resultsContainer.innerHTML =
      '<div class="search-loading"><div class="spinner"></div><p>Searching…</p></div>';
    pagination.innerHTML = '';
    pagination.setAttribute('aria-busy', 'true');

    fetch('/api/search?q=' + encodeURIComponent(query) + '&page=' + page,
          { credentials: 'same-origin' })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) {
            var msg = data && data.detail ? data.detail : 'Search is temporarily unavailable. Please try again.';
            throw new Error(msg);
          }
          return data;
        });
      })
      .then(function (data) {
        // A newer search/page was requested while this one was in flight.
        if (seq !== searchSeq) return;

        if (data.redirect) { window.location.href = data.redirect; return; }

        if (data.limit_reached) {
          showLoginBanner();
          resultsContainer.innerHTML =
            '<div class="no-results">' +
              '<div class="no-results-icon">🔒</div>' +
              '<h3>Free searches used up</h3>' +
              '<p><a href="login.html">Sign in</a> or <a href="signup.html">create an account</a> for unlimited results.</p>' +
            '</div>';
          return;
        }

        if (lucky && data.results && data.results.length) {
          window.location.href = data.results[0].url; return;
        }

        if (!lucky) writeSearchCache(cacheKey, data);
        currentPage = data.page || page;
        if (historyMode) updateUrl(query, currentPage, historyMode, currentMode);
        renderResults(data);
      })
      .catch(function (err) {
        if (seq !== searchSeq) return;
        pagination.innerHTML = '';
        resultsContainer.innerHTML =
          '<div class="no-results"><div class="no-results-icon">⚠️</div>' +
          '<h3>Something went wrong</h3><p>' +
          esc(err && err.message ? err.message : 'Check your connection and try again.') +
          '</p></div>';
      })
      .finally(function () {
        if (seq === searchSeq) pagination.setAttribute('aria-busy', 'false');
      });
  }

  // ---------- Image search ----------
  function performImageSearch(query, page, historyMode) {
    currentQuery = query;
    currentPage  = page;
    var seq = ++searchSeq;

    document.body.classList.add('searching');
    searchSection.classList.add('compact');
    if (globeSection) globeSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');

    resultsContainer.innerHTML =
      '<div class="search-loading"><div class="spinner"></div><p>Searching images…</p></div>';
    pagination.innerHTML = '';
    pagination.setAttribute('aria-busy', 'true');

    fetch('/api/images?q=' + encodeURIComponent(query) + '&page=' + page,
          { credentials: 'same-origin' })
      .then(function (r) {
        return r.json().then(function (data) {
          if (!r.ok) {
            var msg = data && data.detail ? data.detail : 'Image search is temporarily unavailable.';
            throw new Error(msg);
          }
          return data;
        });
      })
      .then(function (data) {
        if (seq !== searchSeq) return;
        currentPage = data.page || page;
        if (historyMode) updateUrl(query, currentPage, historyMode, currentMode);
        renderImageResults(data);
      })
      .catch(function (err) {
        if (seq !== searchSeq) return;
        pagination.innerHTML = '';
        resultsContainer.innerHTML =
          '<div class="no-results"><div class="no-results-icon">⚠️</div>' +
          '<h3>Images unavailable</h3><p>' +
          esc(err && err.message ? err.message : 'Check your connection and try again.') +
          '</p></div>';
      })
      .finally(function () {
        if (seq === searchSeq) pagination.setAttribute('aria-busy', 'false');
      });
  }

  // ---------- Render results ----------
  function renderResults(data) {
    if (currentMode === 'ai') { renderAIResults(data); return; }
    if (currentMode === 'code') { renderCodeResults(data); return; }

    var results = data.results || [];
    var news    = data.news    || [];
    var answer  = data.answer  || null;
    var wiki    = data.wikipedia || null;
    var videos  = data.videos  || [];

    var page = data.page || currentPage || 1;

    if (!results.length && !news.length && !answer && !wiki && !videos.length) {
      resultsContainer.innerHTML =
        page > 1
          ? '<div class="no-results"><div class="no-results-icon">🔍</div>' +
              '<h3>No more results</h3><p>You have reached the end of the results for "<strong>' +
              esc(currentQuery) + '</strong>".</p></div>'
          : '<div class="no-results"><div class="no-results-icon">🔍</div>' +
              '<h3>No results found</h3><p>Try different keywords for "<strong>' +
              esc(currentQuery) + '</strong>".</p></div>';
      pagination.innerHTML = '';
      return;
    }

    var html = '';

    // ── Results count bar ──
    var totalLabel = (data.total || results.length) + (data.has_more ? '+' : '');
    html += page > 1
      ? '<div class="results-info">Page <strong>' + page + '</strong> — results for "<strong>' +
          esc(currentQuery) + '</strong>"</div>'
      : '<div class="results-info">About <strong>' + totalLabel +
          '</strong> results for "<strong>' + esc(currentQuery) + '</strong>"</div>';

    // ── Quick answer / meaning ──
    if (answer) html += buildAnswerCard(answer);

    // ── Wikipedia article ──
    if (wiki) html += buildWikiCard(wiki);

    // ── YouTube videos ──
    if (videos.length) html += buildVideosSection(videos);

    // ── Web results ──
    results.forEach(function (r, i) { html += buildResultCard(r, i + 1); });

    // ── Click-popularity note ──
    if (results.length) {
      html +=
        '<p class="ranking-note">Results are ordered by what people on 8search click most. ' +
          '<button type="button" class="ranking-help" id="rankingHelp">How ranking works</button>' +
        '</p>';
    }

    // ── In the news ──
    if (news.length) html += buildNewsSection(news);

    resultsContainer.innerHTML = html;
    wireAnswerToggle();
    var rankingHelp = document.getElementById('rankingHelp');
    if (rankingHelp) {
      rankingHelp.addEventListener('click', function () { openInfo('ranking'); });
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });

    renderPagination(page, data);
  }

  function renderAIResults(data) {
    var results = data.results || [];
    var answer  = data.answer || null;
    var wiki    = data.wikipedia || null;
    var videos  = data.videos || [];
    var page    = data.page || currentPage || 1;

    if (!results.length && !answer && !wiki && !videos.length) {
      resultsContainer.innerHTML =
        '<div class="no-results"><div class="no-results-icon">🔍</div>' +
          '<h3>No answer found</h3><p>Try asking a more specific question.</p></div>';
      pagination.innerHTML = '';
      return;
    }

    var html =
      '<div class="results-info">AI answer for "<strong>' + esc(currentQuery) +
      '</strong>"</div>';

    if (answer) {
      html += buildAnswerCard(answer);
    } else {
      html +=
        '<div class="ai-empty">' +
          '<span class="ai-empty-mark">8</span>' +
          '<div><h3>No instant answer for this one</h3>' +
          '<p>Here are the most useful sources we found instead.</p></div>' +
        '</div>';
    }

    if (wiki) html += buildWikiCard(wiki);
    if (videos.length && page === 1) html += buildVideosSection(videos.slice(0, 3));

    if (results.length) {
      html += '<div class="ai-sources"><div class="ai-sources-head">Sources</div>';
      results.slice(0, 5).forEach(function (r, i) {
        html += buildResultCard(r, i + 1);
      });
      html += '</div>';
    }

    html +=
      '<button type="button" class="ai-all-btn" id="aiAllBtn">' +
        'See all web results' +
      '</button>';

    resultsContainer.innerHTML = html;
    wireAnswerToggle();

    var aiAllBtn = document.getElementById('aiAllBtn');
    if (aiAllBtn) {
      aiAllBtn.addEventListener('click', function () {
        setMode('web', { rerun: true });
      });
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
    renderPagination(page, data);
  }

  function renderCodeResults(data) {
    var results = data.results || [];
    var page    = data.page || currentPage || 1;

    if (!results.length) {
      resultsContainer.innerHTML =
        '<div class="no-results"><div class="no-results-icon">⌘</div>' +
          '<h3>No code results found</h3><p>Try a library, language, or error message.</p></div>';
      pagination.innerHTML = '';
      return;
    }

    var q = encodeURIComponent(currentQuery);
    var html =
      '<div class="results-info">Code results for "<strong>' + esc(currentQuery) +
      '</strong>"</div>' +
      '<div class="code-banner">' +
        '<div><span class="code-banner-kicker">Developer search</span>' +
        '<strong>Keep digging in the right place</strong></div>' +
        '<div class="code-banner-links">' +
          '<a href="https://github.com/search?q=' + escAttr(q) +
            '&type=repositories" target="_blank" rel="noopener">GitHub</a>' +
          '<a href="https://stackoverflow.com/search?q=' + escAttr(q) +
            '" target="_blank" rel="noopener">Stack Overflow</a>' +
        '</div>' +
      '</div>';

    results.forEach(function (r, i) { html += buildResultCard(r, i + 1); });

    resultsContainer.innerHTML = html;
    window.scrollTo({ top: 0, behavior: 'smooth' });
    renderPagination(page, data);
  }

  function renderImageResults(data) {
    var images = data.images || [];
    var page   = data.page || currentPage || 1;

    if (!images.length) {
      resultsContainer.innerHTML =
        '<div class="no-results"><div class="no-results-icon">🖼️</div>' +
          '<h3>No images found</h3><p>Try a different, more visual search.</p>' +
          '<button type="button" class="link-btn" id="imagesWebBtn">Search the web instead</button>' +
        '</div>';
      pagination.innerHTML = '';
      var imagesWebBtn = document.getElementById('imagesWebBtn');
      if (imagesWebBtn) {
        imagesWebBtn.addEventListener('click', function () {
          setMode('web', { rerun: true });
        });
      }
      return;
    }

    var html =
      '<div class="results-info">Images for "<strong>' + esc(currentQuery) +
      '</strong>"</div><div class="image-grid">';

    images.forEach(function (img) {
      var target = img.url || img.image || '';
      var domain = target ? domainOf(target) : '';
      var title  = img.title || domain || 'Image result';
      html +=
        '<a class="image-card" href="' + escAttr(target) + '" target="_blank" rel="noopener" ' +
           'title="' + escAttr(title) + '">' +
          '<span class="image-thumb">' +
            '<img src="' + escAttr(img.thumbnail || img.image) + '" alt="' +
              escAttr(title) + '" loading="lazy" ' +
              'onerror="this.parentElement.classList.add(\'is-empty\'); this.remove()">' +
          '</span>' +
          '<span class="image-card-foot">' +
            '<span class="image-card-title">' + esc(title) + '</span>' +
            (domain ? '<span class="image-card-source">' + esc(domain) + '</span>' : '') +
          '</span>' +
        '</a>';
    });

    html += '</div>';
    resultsContainer.innerHTML = html;
    window.scrollTo({ top: 0, behavior: 'smooth' });

    renderPagination(page, {
      has_more: !!data.has_more,
      max_page: 5
    });
  }

  function buildAnswerCard(a) {
    var kicker = a.kind === 'definition' ? 'Meaning' : 'Quick answer';
    var text   = a.text || '';
    var expandable = text.length > 240;
    var token = a.click_token || '';
    var source = a.url
      ? '<a class="answer-source" href="' + escAttr(a.url) + '" target="_blank" rel="noopener"' +
          clickAttrs('answer', a.url, a.title || currentQuery, a.click_position || 1, token) + '>Source: ' +
          esc(a.source || 'the web') + '</a>'
      : '<span class="answer-source">' + esc(a.source || '') + '</span>';

    return (
      '<section class="answer-card">' +
        '<div class="answer-kicker">' + kicker + '</div>' +
        '<div class="answer-title">' + esc(a.title || currentQuery) + '</div>' +
        (a.part_of_speech ? '<div class="answer-pos">' + esc(a.part_of_speech) + '</div>' : '') +
        '<div class="answer-text" id="answerText">' + esc(text) + '</div>' +
        '<div class="answer-footer">' +
          source +
          (expandable
            ? '<button type="button" class="answer-toggle" id="answerToggle" aria-expanded="false">Show more</button>'
            : '') +
        '</div>' +
      '</section>'
    );
  }

  function wireAnswerToggle() {
    var button = document.getElementById('answerToggle');
    var text   = document.getElementById('answerText');
    if (!button || !text) return;
    button.addEventListener('click', function () {
      var expanded = text.classList.toggle('expanded');
      button.textContent = expanded ? 'Show less' : 'Show more';
      button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    });
  }

  function buildWikiCard(wiki) {
    var url = wiki.url || '';
    return (
      '<a class="wiki-card" href="' + escAttr(url) + '" target="_blank" rel="noopener"' +
        clickAttrs('wiki', url, wiki.title || '', wiki.click_position || 1, wiki.click_token || '') + '>' +
        '<div class="wiki-top"><span class="wiki-mark">W</span><span>Wikipedia</span></div>' +
        '<div class="wiki-title">' + esc(wiki.title || '') + '</div>' +
        '<div class="wiki-extract">' + esc(wiki.extract || wiki.description || '') + '</div>' +
        '<div class="wiki-url">' + esc(makeBreadcrumb(url)) + '</div>' +
      '</a>'
    );
  }

  function buildVideosSection(videos) {
    var html =
      '<section class="videos-section">' +
        '<div class="videos-heading">Videos</div>' +
        '<div class="video-list">';

    videos.forEach(function (v, i) {
      var meta = [v.channel, v.published].filter(Boolean).join(' · ');
      html +=
        '<a class="video-row" href="' + escAttr(v.url) + '" target="_blank" rel="noopener"' +
          clickAttrs('video', v.url, v.title || '', v.click_position || (i + 1), v.click_token || '') + '>' +
          '<div class="video-thumb' + (v.thumbnail ? '' : ' is-empty') + '">' +
            (v.thumbnail
              ? '<img src="' + escAttr(v.thumbnail) + '" alt="" loading="lazy" ' +
                'onerror="this.parentElement.classList.add(\'is-empty\'); this.remove()">'
              : '') +
            (v.duration ? '<span class="video-duration">' + esc(v.duration) + '</span>' : '') +
          '</div>' +
          '<div class="video-info">' +
            '<div class="video-title">' + esc(v.title || '') + '</div>' +
            (meta ? '<div class="video-meta">' + esc(meta) + '</div>' : '') +
          '</div>' +
        '</a>';
    });

    return html + '</div></section>';
  }

  function buildNewsSection(news) {
    var html =
      '<section class="news-section">' +
        '<div class="news-heading">In the news</div>' +
        '<div class="news-grid">';

    news.forEach(function (n, i) {
      var domain = domainOf(n.url);
      var favicon = 'https://www.google.com/s2/favicons?sz=16&domain=' + encodeURIComponent(domain);
      var timeAgo = n.date ? relativeTime(n.date) : '';
      html +=
        '<a class="news-card" href="' + escAttr(n.url) + '" target="_blank" rel="noopener"' +
          clickAttrs('news', n.url, n.title || '', n.click_position || (i + 1), n.click_token || '') + '>' +
          (n.image
            ? '<div class="news-card-img"><img src="' + escAttr(n.image) + '" alt="" loading="lazy" onerror="this.parentElement.style.display=\'none\'"></div>'
            : '') +
          '<div class="news-card-body">' +
            '<div class="news-card-source">' +
              '<img src="' + escAttr(favicon) + '" width="14" height="14" alt="">' +
              '<span>' + esc(n.source || domain) + '</span>' +
            '</div>' +
            '<div class="news-card-title">' + esc(n.title) + '</div>' +
            (timeAgo ? '<div class="news-card-time">' + timeAgo + '</div>' : '') +
          '</div>' +
        '</a>';
    });

    return html + '</div></section>';
  }

  function buildResultCard(r, position) {
    var domain     = domainOf(r.url);
    var breadcrumb = makeBreadcrumb(r.url);
    var favicon    = 'https://www.google.com/s2/favicons?sz=16&domain=' + encodeURIComponent(domain);
    var clicks     = parseInt(r.click_count || 0, 10) || 0;
    var activePos  = parseInt(r.click_position || position || 0, 10) || 0;
    var badge      = clicks > 0
      ? '<div class="result-popularity">🔥 Popular on 8search · ' + clicks +
          ' click' + (clicks === 1 ? '' : 's') + '</div>'
      : '';

    return (
      '<div class="result-item">' +
        '<div class="result-url">' +
          '<img class="result-favicon" src="' + escAttr(favicon) + '" width="16" height="16" alt="" ' +
               'onerror="this.style.display=\'none\'">' +
          '<span class="result-breadcrumb">' + esc(breadcrumb) + '</span>' +
          (r.source ? '<span class="result-source">' + esc(r.source) + '</span>' : '') +
        '</div>' +
        '<a class="result-title" href="' + escAttr(r.url) + '" target="_blank" rel="noopener"' +
          clickAttrs('web', r.url, r.title || '', activePos, r.click_token || '') + '>' +
          esc(r.title || 'Untitled') +
        '</a>' +
        badge +
        '<div class="result-snippet">' + esc(r.snippet || '') + '</div>' +
      '</div>'
    );
  }

  // ---------- Pagination ----------
  function pageButton(page, label, extraClass) {
    var active = extraClass === 'active';
    return '<button type="button" class="page-btn' +
      (extraClass ? ' ' + extraClass : '') +
      '" data-page="' + page + '"' +
      (active ? ' aria-current="page"' : '') + '>' + label + '</button>';
  }

  function renderPagination(current, data) {
    var maxPage = (data && data.max_page) || MAX_PAGE;
    var hasMore = !!(data && data.has_more);

    if (!hasMore && current === 1) {
      pagination.innerHTML = '';
      return;
    }

    var start, end;
    if (hasMore) {
      // Slide a five-page window around the current page. While browsing the
      // first pages this gives exactly "1 2 3 4 5  Next".
      start = Math.max(1, current - 2);
      end = Math.min(maxPage, start + PAGE_WINDOW - 1);
      if (end - start + 1 < PAGE_WINDOW) start = Math.max(1, end - PAGE_WINDOW + 1);
    } else {
      end = current;
      start = Math.max(1, current - PAGE_WINDOW + 1);
    }

    var html = '';
    if (current > 1)
      html += pageButton(current - 1, '&laquo; Prev', 'page-prev');

    if (start > 1) {
      html += pageButton(1, '1');
      if (start > 2) html += '<span class="page-ellipsis" aria-hidden="true">…</span>';
    }

    for (var i = start; i <= end; i++) {
      html += pageButton(i, String(i), i === current ? 'active' : '');
    }

    if (hasMore && current < maxPage)
      html += pageButton(current + 1, 'Next &raquo;', 'page-next');

    pagination.innerHTML = html;
  }

  // Delegated once instead of re-binding every button on every render.
  pagination.addEventListener('click', function (e) {
    var btn = e.target.closest ? e.target.closest('.page-btn[data-page]') : null;
    if (!btn || btn.disabled) return;
    var page = parseInt(btn.dataset.page, 10);
    if (!page || page === currentPage) return;
    performSearch(currentQuery, page, false, 'push');
  });

  // ---------- Login Banner ----------
  function showLoginBanner() { loginBanner.classList.remove('hidden'); }
  if (bannerDismiss) bannerDismiss.addEventListener('click', function () {
    loginBanner.classList.add('hidden');
  });

  // ---------- Feedback ----------
  function setFeedbackStatus(text, kind) {
    if (!feedbackStatus) return;
    feedbackStatus.textContent = text;
    feedbackStatus.className = 'feedback-status' + (kind ? ' ' + kind : '');
  }

  if (feedbackForm) {
    feedbackForm.addEventListener('submit', function (e) {
      e.preventDefault();
      if (feedbackSubmit.disabled) return;

      var name = feedbackName.value.trim();
      var email = feedbackEmail.value.trim();
      var message = feedbackMessage.value.trim();

      if (message.length < 3) {
        setFeedbackStatus('Please write a message before sending.', 'error');
        feedbackMessage.focus();
        return;
      }

      if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        setFeedbackStatus('Please enter a valid email address.', 'error');
        feedbackEmail.focus();
        return;
      }

      feedbackSubmit.disabled = true;
      feedbackSubmit.textContent = 'Sending…';
      setFeedbackStatus('Sending your feedback…', '');

      fetch('/api/feedback', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, email: email, message: message })
      })
        .then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (data) {
            if (!r.ok) {
              var detail = data && data.detail;
              var err = new Error(typeof detail === 'string'
                ? detail
                : 'Something went wrong. Please try again.');
              err.status = r.status;
              throw err;
            }
            return data;
          });
        })
        .then(function (data) {
          feedbackForm.reset();
          if (feedbackEmail && currentUser) feedbackEmail.value = currentUser;
          setFeedbackStatus(
            (data && data.message) || 'Thank you! Your feedback has been sent.',
            'success'
          );
        })
        .catch(function (err) {
          setFeedbackStatus(err.message || 'Something went wrong. Please try again.', 'error');
        })
        .then(function () {
          feedbackSubmit.disabled = false;
          feedbackSubmit.textContent = 'Send feedback';
        });
    });
  }

  // ---------- Helpers ----------
  function domainOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return url; }
  }

  function makeBreadcrumb(url) {
    try {
      var u = new URL(url);
      var parts = [u.hostname.replace(/^www\./, '')];
      var segs  = u.pathname.split('/').filter(Boolean);
      segs.forEach(function (s) { parts.push(decodeURIComponent(s).replace(/_/g, ' ')); });
      return parts.join(' › ');
    } catch (e) { return url; }
  }

  function relativeTime(dateStr) {
    try {
      var diff = Date.now() - new Date(dateStr).getTime();
      var mins  = Math.floor(diff / 60000);
      var hours = Math.floor(diff / 3600000);
      var days  = Math.floor(diff / 86400000);
      if (mins  < 60)  return mins  + ' minute'  + (mins  !== 1 ? 's' : '') + ' ago';
      if (hours < 24)  return hours + ' hour'    + (hours !== 1 ? 's' : '') + ' ago';
      return days + ' day' + (days !== 1 ? 's' : '') + ' ago';
    } catch (e) { return ''; }
  }

  function esc(str) {
    if (!str) return '';
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function escAttr(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;')
                      .replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ---------- Init ----------
  window.addEventListener('popstate', function () {
    var route = readRoute();
    if (!route.q) { goHome(false); return; }
    setMode(route.mode, { rerun: false });
    searchInput.value = route.q;
    performSearch(route.q, route.page, false, null);
  });

  checkAuth();
  setMode('web');
  renderCustomShortcuts();

  var initialRoute = readRoute();
  if (initialRoute.q) {
    setMode(initialRoute.mode, { rerun: false });
    searchInput.value = initialRoute.q;
    performSearch(initialRoute.q, initialRoute.page, false, null);
  }

  window.EightSearch = {
    showLoginBanner: showLoginBanner,
    setMode: setMode
  };
})();
