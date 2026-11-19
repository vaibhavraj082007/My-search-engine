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
  var istClock        = document.getElementById('istClock') || document.getElementById('utcClock');
  var topDate         = document.getElementById('topDate');
  var globeSection    = document.querySelector('.globe-section');
  var signinPrompt    = document.getElementById('signinPrompt');
  var signinBackdrop  = document.getElementById('signinBackdrop');
  var signinClose     = document.getElementById('signinClose');
  var signinContinue  = document.getElementById('signinContinue');
  var signinSignup    = document.getElementById('signinSignup');
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
  var trendingPeek    = document.getElementById('trendingPeek');
  var askAiFab        = document.getElementById('askAiFab');
  var historyDialog   = document.getElementById('historyDialog');
  var historyList     = document.getElementById('historyList');
  var historyEmpty    = document.getElementById('historyEmpty');
  var historyClose    = document.getElementById('historyClose');
  var historyFooter   = document.getElementById('historyFooter');
  var historyLoadMore = document.getElementById('historyLoadMore');
  var historyClear    = document.getElementById('historyClear');
  var historyConfirm  = document.getElementById('historyConfirm');
  var historyClearConfirm = document.getElementById('historyClearConfirm');
  var historyClearCancel  = document.getElementById('historyClearCancel');
  var historySummary  = document.getElementById('historySummary');
  var historyStatus   = document.getElementById('historyStatus');

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
  var HISTORY_PAGE_SIZE = 50;
  var HISTORY_EMPTY_TEXT = 'No searches yet. Your searches will appear here after you search while signed in.';
  var HISTORY_DEFAULT_SUMMARY = 'Only you can see this. Searches are saved when you are signed in.';
  var TAB_LABELS = { web: 'Web', ai: 'AI Answer', images: 'Images', code: 'Code' };
  var pendingHistoryRecord = null;
  var recentHistoryCache = { items: [], at: 0 };
  var historyState = {
    items: [],
    total: 0,
    hasMore: false,
    loading: false,
    seq: 0,
    loadedAt: 0
  };

  var MODE_PLACEHOLDERS = {
    web:      'Search anything or type a calculation…',
    ai:       'Ask a question and get a direct answer…',
    images:   'Search for images…',
    code:     'Search code, repos, and documentation…'
  };

  // ---------- Indian Standard Time (IST) Clock & Date ----------
  function updateIndianDateTime() {
    var now = new Date();
    if (istClock) {
      try {
        var timeFormatter = new Intl.DateTimeFormat('en-US', {
          timeZone: 'Asia/Kolkata',
          hour: 'numeric',
          minute: '2-digit',
          second: '2-digit',
          hour12: true
        });
        var parts = timeFormatter.formatToParts(now);
        var p = {};
        for (var i = 0; i < parts.length; i++) {
          p[parts[i].type] = parts[i].value;
        }
        var hour = p.hour || '12';
        var minute = p.minute || '00';
        var second = p.second || '00';
        var dayPeriod = (p.dayPeriod || 'PM').toUpperCase();
        istClock.innerHTML = '<span class="clock-hm">' + hour + ':' + minute + '</span><span class="clock-sec">:' + second + '</span> <span class="clock-ampm">' + dayPeriod + '</span><span class="clock-zone"> IST</span>';
      } catch (e) {
        var istOffset = 5.5 * 60 * 60 * 1000;
        var istDate = new Date(now.getTime() + istOffset);
        var h = istDate.getUTCHours();
        var ampm = h >= 12 ? 'PM' : 'AM';
        h = h % 12;
        if (h === 0) h = 12;
        var hh = String(h);
        var mm = String(istDate.getUTCMinutes()).padStart(2, '0');
        var ss = String(istDate.getUTCSeconds()).padStart(2, '0');
        istClock.innerHTML = '<span class="clock-hm">' + hh + ':' + mm + '</span><span class="clock-sec">:' + ss + '</span> <span class="clock-ampm">' + ampm + '</span><span class="clock-zone"> IST</span>';
      }
    }

    if (topDate) {
      try {
        var dateFormatter = new Intl.DateTimeFormat('en-GB', {
          timeZone: 'Asia/Kolkata',
          weekday: 'short',
          day: 'numeric',
          month: 'short',
          year: 'numeric'
        });
        var dparts = dateFormatter.formatToParts(now);
        var dp = {};
        for (var j = 0; j < dparts.length; j++) {
          dp[dparts[j].type] = dparts[j].value;
        }
        var weekday = dp.weekday ? dp.weekday + ', ' : '';
        var day = dp.day || '1';
        var month = dp.month || 'Jan';
        var year = dp.year ? ' ' + dp.year : '';
        topDate.innerHTML = '<span class="date-day">' + weekday + '</span><span class="date-main">' + day + ' ' + month + '</span><span class="date-year">' + year + '</span>';
      } catch (e) {
        var days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        var istOffset2 = 5.5 * 60 * 60 * 1000;
        var istDate2 = new Date(now.getTime() + istOffset2);
        var w = days[istDate2.getUTCDay()] + ', ';
        var d = istDate2.getUTCDate() + ' ' + months[istDate2.getUTCMonth()];
        var y = ' ' + istDate2.getUTCFullYear();
        topDate.innerHTML = '<span class="date-day">' + w + '</span><span class="date-main">' + d + '</span><span class="date-year">' + y + '</span>';
      }
    }
  }
  updateIndianDateTime();
  setInterval(updateIndianDateTime, 1000);

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
  function warmRecentHistory() {
    if (!currentUser) return;
    if (recentHistoryCache.at &&
        Date.now() - recentHistoryCache.at < 20000) {
      return;
    }
    fetch('/api/history?limit=5', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('history unavailable');
        return r.json();
      })
      .then(function (data) {
        if (!currentUser) return;
        recentHistoryCache = {
          items: data && Array.isArray(data.items) ? data.items : [],
          at: Date.now()
        };
      })
      .catch(function () {
        // The search box still works when history is unavailable.
      });
  }

  function checkAuth() {
    fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) {
        if (!d || !d.email) throw new Error('guest');
        currentUser = d.email;
        if (feedbackEmail && !feedbackEmail.value) feedbackEmail.value = currentUser;
        renderUserArea();
        invalidateHistoryCache();
        // A search restored from the in-tab cache may have run before this
        // request proved the visitor is signed in. Record it now.
        if (pendingHistoryRecord) {
          recordHistory(pendingHistoryRecord.query, pendingHistoryRecord.tab);
          pendingHistoryRecord = null;
        }
        // Warm the recent-search cache so the first click on the search box
        // opens instantly. Do not show the panel until the visitor asks for
        // it; autofocus alone should not cover the page on load.
        warmRecentHistory();
      })
      .catch(function () {
        currentUser = null;
        pendingHistoryRecord = null;
        recentHistoryCache = { items: [], at: 0 };
        if (suggestState.kind === 'history') closeSuggestions();
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
          '<button class="logout-btn history-btn" id="historyBtn" type="button">History</button>' +
          '<button class="logout-btn" id="logoutBtn" type="button">Sign out</button>' +
        '</div>';
      document.getElementById('logoutBtn').addEventListener('click', handleLogout);
      var historyBtn = document.getElementById('historyBtn');
      if (historyBtn) historyBtn.addEventListener('click', openHistory);
    } else {
      userArea.innerHTML =
        '<a href="' + escAttr(authUrl('/login')) + '" class="sign-in-link">Sign in</a>';
    }
    syncAuthLinks();
  }

  function handleLogout() {
    fetch('/api/logout', { method: 'POST', credentials: 'same-origin' })
      .finally(function () {
        currentUser = null;
        pendingHistoryRecord = null;
        recentHistoryCache = { items: [], at: 0 };
        historyState.items = [];
        historyState.total = 0;
        historyState.hasMore = false;
        historyState.seq += 1;
        if (historyDialog && historyDialog.open) historyDialog.close();
        if (suggestState.kind === 'history') closeSuggestions();
        renderUserArea();
        goHome();
      });
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
    if (trendingPeek) trendingPeek.classList.remove('hidden');
    closeSuggestions();
    searchInput.value = '';
    currentQuery = '';
    currentPage  = 1;
    searchSeq    = 0;
    document.title = '8search';
    setMode('web');
    syncAuthLinks();

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

  // ---------- Live suggestions + recent history ----------
  var suggestState = {
    timer: null,
    controller: null,
    items: [],
    active: -1,
    seq: 0,
    lastQuery: '',
    kind: ''
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
    suggestState.kind = '';
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

  function chooseSuggestion(entry) {
    var text = typeof entry === 'string' ? entry : entry && entry.text;
    var kind = typeof entry === 'string' ? 'web' : ((entry && entry.kind) || 'web');
    if (kind === 'action') {
      closeSuggestions();
      openHistory();
      return;
    }
    if (!text) return;
    searchInput.value = text;
    closeSuggestions();
    if (kind === 'history' && entry.tab && entry.tab !== currentMode) {
      setMode(entry.tab, { rerun: false });
    }
    doSearch(text);
  }

  function renderSuggestions(items, typed, view) {
    if (!suggestionsEl) return;
    suggestState.items = items.slice(0, 9);
    suggestState.active = -1;
    suggestState.kind = view || 'suggestions';
    suggestionsEl.replaceChildren();
    if (!suggestState.items.length) {
      suggestionsEl.classList.add('hidden');
      searchInput.setAttribute('aria-expanded', 'false');
      return;
    }

    suggestionsEl.setAttribute(
      'aria-label',
      view === 'history'
        ? 'Recent searches. Only you can see these.'
        : 'Search suggestions'
    );

    if (view === 'history') {
      var heading = document.createElement('div');
      heading.className = 'suggestion-heading';
      heading.setAttribute('aria-hidden', 'true');
      var headingLabel = document.createElement('span');
      headingLabel.textContent = 'Recent searches';
      var headingPrivacy = document.createElement('span');
      headingPrivacy.className = 'suggestion-private';
      headingPrivacy.textContent = 'Only you';
      heading.appendChild(headingLabel);
      heading.appendChild(headingPrivacy);
      suggestionsEl.appendChild(heading);
    }

    suggestState.items.forEach(function (entry, index) {
      var text = typeof entry === 'string' ? entry : entry.text;
      if (!text) return;
      var kind = typeof entry === 'string' ? 'web' : (entry.kind || 'web');
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'suggestion-item';
      if (kind === 'action') button.className += ' suggestion-action';
      button.id = 'suggestion-' + index;
      button.setAttribute('role', 'option');
      button.setAttribute('aria-selected', 'false');

      var icon = document.createElement('span');
      icon.className = 'suggestion-icon suggestion-icon-' + kind;
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = kind === 'popular' ? '↗'
        : (kind === 'local' ? '⌕'
        : (kind === 'history' ? '↺'
        : (kind === 'action' ? '→' : 'W')));

      var label = document.createElement('span');
      label.className = 'suggestion-text';
      label.textContent = text;

      var hint = document.createElement('span');
      hint.className = 'suggestion-kind';
      hint.textContent = kind === 'popular' ? 'Popular'
        : (kind === 'local' ? 'On this site'
        : (kind === 'history'
          ? (TAB_LABELS[(entry && entry.tab) || 'web'] || TAB_LABELS.web)
          : ''));

      button.appendChild(icon);
      button.appendChild(label);
      if (hint.textContent) button.appendChild(hint);
      // pointerdown prevents the input blur before click.
      button.addEventListener('pointerdown', function (e) { e.preventDefault(); });
      button.addEventListener('click', function () { chooseSuggestion(entry); });
      button.addEventListener('mouseenter', function () { updateSuggestionActive(index); });
      suggestionsEl.appendChild(button);
    });

    suggestionsEl.classList.remove('hidden');
    searchInput.setAttribute('aria-expanded', 'true');
  }

  function renderRecentHistory(items) {
    if (!items || !items.length) {
      closeSuggestions();
      return;
    }
    var entries = items.slice(0, 5).map(function (item) {
      return { text: item.query, kind: 'history', tab: item.tab };
    });
    entries.push({ text: 'View all history', kind: 'action' });
    renderSuggestions(entries, '', 'history');
  }

  function showRecentHistory() {
    if (!suggestionsEl) return;
    if (!currentUser || searchInput.value.trim()) {
      closeSuggestions();
      return;
    }
    if (suggestState.kind === 'history' &&
        !suggestionsEl.classList.contains('hidden')) {
      return;
    }
    if (recentHistoryCache.at &&
        Date.now() - recentHistoryCache.at < 20000) {
      renderRecentHistory(recentHistoryCache.items);
      return;
    }

    var seq = ++suggestState.seq;
    if (suggestState.controller) {
      try { suggestState.controller.abort(); } catch (e) {}
    }
    var controller = window.AbortController ? new AbortController() : null;
    suggestState.controller = controller;

    fetch('/api/history?limit=5',
          { credentials: 'same-origin', signal: controller ? controller.signal : undefined })
      .then(function (r) {
        if (!r.ok) throw new Error('history unavailable');
        return r.json();
      })
      .then(function (data) {
        if (seq !== suggestState.seq) return;
        if (!currentUser || searchInput.value.trim()) return;
        var items = data && Array.isArray(data.items) ? data.items : [];
        recentHistoryCache = { items: items, at: Date.now() };
        renderRecentHistory(items);
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') return;
        if (seq === suggestState.seq) closeSuggestions();
      });
  }

  function requestSuggestions(typed) {
    var query = (typed || '').trim();
    if (!query) { showRecentHistory(); return; }
    if (suggestState.kind === 'suggestions' &&
        query === suggestState.lastQuery && suggestState.items.length) return;
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
        renderSuggestions(items, query, 'suggestions');
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
    if (!query) {
      if (suggestState.timer) {
        window.clearTimeout(suggestState.timer);
        suggestState.timer = null;
      }
      showRecentHistory();
      return;
    }
    if (suggestState.timer) window.clearTimeout(suggestState.timer);
    suggestState.timer = window.setTimeout(function () {
      suggestState.timer = null;
      requestSuggestions(query);
    }, 120);
  }

  searchInput.addEventListener('input', scheduleSuggestions);
  searchInput.addEventListener('focus', scheduleSuggestions);
  searchInput.addEventListener('click', scheduleSuggestions);
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
      e.preventDefault();
      chooseSuggestion(suggestState.items[suggestState.active]);
    }
  });

  document.addEventListener('click', function (e) {
    if (!suggestionsEl || suggestionsEl.classList.contains('hidden')) return;
    if (searchForm.contains(e.target)) return;
    closeSuggestions();
  });

  searchForm.addEventListener('focusout', function () {
    window.setTimeout(function () {
      if (!searchForm.contains(document.activeElement)) closeSuggestions();
    }, 120);
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

  // ---------- Ask 8search AI floating shortcut ----------
  if (askAiFab) {
    askAiFab.addEventListener('click', function () {
      if (currentQuery) {
        setMode('ai', { rerun: true });
      } else {
        setMode('ai');
      }
      try {
        searchInput.focus({ preventScroll: false });
      } catch (e) {
        searchInput.focus();
      }
    });
  }

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

  document.querySelectorAll('.footer-link[data-info]').forEach(function (link) {
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
      var q = (params.get('q') || '').trim().slice(0, MAX_QUERY);
      var page = parseInt(params.get('page') || '1', 10);
      var mode = params.get('tab') || params.get('mode') || 'web';
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
      if (searchMode && searchMode !== 'web') params.set('tab', searchMode);
      var url = '/search?' + params.toString();
      var state = { q: query, page: page, mode: searchMode || 'web' };
      if (historyMode === 'push') window.history.pushState(state, '', url);
      else window.history.replaceState(state, '', url);
    } catch (e) {}
  }

  function safeNavigationUrl(value) {
    var raw = (value || '').trim();
    if (!raw) return null;
    try {
      var hasScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(raw);
      var parsed = new URL(hasScheme ? raw : 'https://' + raw);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
      if (!parsed.hostname) return null;
      return parsed.href;
    } catch (e) {
      return null;
    }
  }

  function nextPathForQuery(query, tab, page) {
    var params = new URLSearchParams();
    params.set('q', (query || '').slice(0, MAX_QUERY));
    if (tab && tab !== 'web') params.set('tab', tab);
    if (page && page > 1) params.set('page', String(page));
    return '/search?' + params.toString();
  }

  // Sign-in/sign-up links carry the current search so a guest who hits the
  // limit (or simply chooses to sign in) returns to the same query and tab.
  function authUrl(path) {
    var query = (currentQuery || '').trim();
    if (!query) return path;
    return path + '?next=' + encodeURIComponent(
      nextPathForQuery(query, currentMode, currentPage)
    );
  }

  function syncAuthLinks() {
    var loginHref = authUrl('/login');
    var signupHref = authUrl('/signup');
    var topLink = userArea ? userArea.querySelector('.sign-in-link') : null;
    if (!currentUser && topLink) topLink.href = loginHref;
    var bannerLink = loginBanner ? loginBanner.querySelector('.banner-link') : null;
    if (bannerLink) bannerLink.href = loginHref;
    if (signinContinue) signinContinue.href = loginHref;
    if (signinSignup) signinSignup.href = signupHref;
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

  // ---------- History helpers ----------
  function invalidateHistoryCache() {
    recentHistoryCache.at = 0;
    historyState.loadedAt = 0;
  }

  function recordHistory(query, tab) {
    if (!query) return;
    invalidateHistoryCache();
    try {
      fetch('/api/history', {
        method: 'POST',
        credentials: 'same-origin',
        keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: String(query).slice(0, MAX_QUERY),
          tab: tab || currentMode
        })
      }).catch(function () {});
    } catch (e) {}
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
    q = q.trim().slice(0, MAX_QUERY);
    if (!q) return;
    // URL-like input navigates only to http(s); javascript:/data: and other
    // schemes are treated as ordinary search text.
    if (q.indexOf('.') !== -1 && q.indexOf(' ') === -1) {
      var target = safeNavigationUrl(q);
      if (target) {
        window.location.href = target;
        return;
      }
    }
    performSearch(q, 1, lucky, 'push');
  }

  function renderLimitCard(query, data) {
    showLoginBanner();
    var next = nextPathForQuery(query, currentMode, currentPage);
    var encodedNext = encodeURIComponent(next);
    var loginUrl = (data && data.login_url) || ('/login?next=' + encodedNext);
    var signupUrl = (data && data.signup_url) || ('/signup?next=' + encodedNext);
    resultsContainer.innerHTML =
      '<div class="no-results limit-card">' +
        '<div class="no-results-icon">🔒</div>' +
        '<h3>Sign in to continue</h3>' +
        '<p>Your free searches are used up. Sign in or create a free account to keep searching for <strong>' +
          esc(query) + '</strong>.</p>' +
        '<div class="limit-actions">' +
          '<a class="limit-primary" href="' + escAttr(loginUrl) + '">Sign in</a>' +
          '<a class="limit-secondary" href="' + escAttr(signupUrl) + '">Create an account</a>' +
        '</div>' +
        '<p class="limit-note">Your search is saved and will reopen after you sign in.</p>' +
      '</div>';
    pagination.innerHTML = '';
    syncAuthLinks();
  }

  // ---------- Search ----------
  function performSearch(query, page, lucky, historyMode) {
    query = (query || '').trim().slice(0, MAX_QUERY);
    if (!query) return;
    if (page === 1) invalidateHistoryCache();
    if (currentMode === 'images' && !lucky) {
      performImageSearch(query, page, historyMode);
      return;
    }

    currentQuery = query;
    currentPage  = page;
    var seq = ++searchSeq;
    document.title = query + ' – 8search';
    syncAuthLinks();

    // Switch to results layout
    closeSuggestions();
    document.body.classList.add('searching');
    searchSection.classList.add('compact');
    if (globeSection) globeSection.classList.add('hidden');
    if (trendingNews) trendingNews.classList.add('hidden');
    if (trendingPeek) trendingPeek.classList.add('hidden');
    resultsSection.classList.remove('hidden');

    var cacheKey = searchCacheKey(currentMode, query, page);
    if (!lucky) {
      var cached = readSearchCache(cacheKey);
      if (cached) {
        if (page === 1) {
          if (currentUser) recordHistory(query, currentMode);
          else pendingHistoryRecord = { query: query, tab: currentMode };
        }
        currentPage = cached.page || page;
        syncAuthLinks();
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

    fetch('/api/search?q=' + encodeURIComponent(query) + '&page=' + page +
          '&tab=' + encodeURIComponent(currentMode),
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

        if (data.redirect) {
          var redirect = safeNavigationUrl(data.redirect);
          if (redirect) window.location.href = redirect;
          return;
        }

        if (data.limit_reached) {
          currentPage = page;
          if (historyMode) updateUrl(query, page, historyMode, currentMode);
          renderLimitCard(query, data);
          return;
        }

        if (lucky && data.results && data.results.length) {
          var luckyUrl = safeNavigationUrl(data.results[0].url);
          if (luckyUrl) window.location.href = luckyUrl;
          return;
        }

        if (!lucky) writeSearchCache(cacheKey, data);
        currentPage = data.page || page;
        syncAuthLinks();
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
    query = (query || '').trim().slice(0, MAX_QUERY);
    if (!query) return;
    if (page === 1) invalidateHistoryCache();
    currentQuery = query;
    currentPage  = page;
    var seq = ++searchSeq;
    document.title = query + ' – 8search';
    syncAuthLinks();

    closeSuggestions();
    document.body.classList.add('searching');
    searchSection.classList.add('compact');
    if (globeSection) globeSection.classList.add('hidden');
    if (trendingNews) trendingNews.classList.add('hidden');
    if (trendingPeek) trendingPeek.classList.add('hidden');
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
        if (data.limit_reached) {
          currentPage = page;
          if (historyMode) updateUrl(query, page, historyMode, currentMode);
          renderLimitCard(query, data);
          return;
        }
        currentPage = data.page || page;
        syncAuthLinks();
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

  // ---------- Per-account search history ----------
  function openHistory() {
    if (!currentUser) {
      showSigninPrompt();
      return;
    }
    if (!historyDialog) return;
    closeSuggestions();
    hideHistoryConfirm();
    historyEmpty.textContent = HISTORY_EMPTY_TEXT;
    historyEmpty.classList.add('hidden');
    historyList.replaceChildren();
    historyState.items = [];
    historyState.total = 0;
    historyState.hasMore = false;
    historyState.loading = false;
    historyState.seq += 1;
    historySummary.textContent = HISTORY_DEFAULT_SUMMARY;
    historyStatus.textContent = '';
    updateHistoryFooter();
    if (!historyDialog.open) {
      if (typeof historyDialog.showModal === 'function') historyDialog.showModal();
      else historyDialog.setAttribute('open', '');
    }
    loadHistory(false);
  }

  function closeHistory() {
    if (historyDialog && historyDialog.open) historyDialog.close();
  }

  function hideHistoryConfirm() {
    if (historyConfirm) historyConfirm.classList.add('hidden');
    updateHistoryFooter();
  }

  function showHistoryConfirm() {
    if (!historyConfirm) return;
    historyConfirm.classList.remove('hidden');
    if (historyClear) historyClear.classList.add('hidden');
    if (historyClearCancel) historyClearCancel.focus();
  }

  function updateHistoryFooter() {
    if (!historyFooter) return;
    var hasItems = historyState.items.length > 0;
    if (historyLoadMore) {
      historyLoadMore.classList.toggle('hidden', !historyState.hasMore);
      historyLoadMore.disabled = historyState.loading;
      historyLoadMore.textContent = historyState.loading ? 'Loading…' : 'Load more';
    }
    if (historyClear) historyClear.classList.toggle('hidden', !hasItems);
    historyFooter.classList.toggle('hidden', !hasItems && !historyState.hasMore);
  }

  function historyTabLabel(tab) {
    return TAB_LABELS[tab] || TAB_LABELS.web;
  }

  function renderHistoryItems() {
    if (!historyList) return;
    historyList.replaceChildren();
    var items = historyState.items;

    if (!items.length) {
      historyEmpty.textContent = HISTORY_EMPTY_TEXT;
      historyEmpty.classList.remove('hidden');
      historySummary.textContent = HISTORY_DEFAULT_SUMMARY;
      updateHistoryFooter();
      return;
    }

    historyEmpty.classList.add('hidden');
    historySummary.textContent = 'Only you can see this. ' + historyState.total +
      ' saved search' + (historyState.total === 1 ? '' : 'es') + '.';

    items.forEach(function (item) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'history-item';

      var icon = document.createElement('span');
      icon.className = 'history-item-icon';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = '↺';

      var text = document.createElement('span');
      text.className = 'history-item-text';

      var query = document.createElement('span');
      query.className = 'history-item-query';
      query.textContent = item.query;
      query.title = item.query;

      var meta = document.createElement('span');
      meta.className = 'history-item-meta';
      meta.textContent = historyTabLabel(item.tab) +
        (item.searched_at ? ' · ' + relativeTime(item.searched_at) : '');

      var arrow = document.createElement('span');
      arrow.className = 'history-item-arrow';
      arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = '→';

      text.appendChild(query);
      text.appendChild(meta);
      button.appendChild(icon);
      button.appendChild(text);
      button.appendChild(arrow);
      button.addEventListener('click', function () {
        closeHistory();
        if (item.tab && item.tab !== currentMode) {
          setMode(item.tab, { rerun: false });
        }
        searchInput.value = item.query;
        doSearch(item.query);
      });
      historyList.appendChild(button);
    });

    updateHistoryFooter();
  }

  function loadHistory(append) {
    if (!currentUser || !historyDialog || historyState.loading) return;
    historyState.loading = true;
    var seq = ++historyState.seq;
    var offset = append ? historyState.items.length : 0;
    if (!append) {
      historyList.replaceChildren();
      historyEmpty.classList.add('hidden');
      historyList.setAttribute('aria-busy', 'true');
    }
    historyStatus.textContent = 'Loading your history…';
    updateHistoryFooter();

    fetch('/api/history?limit=' + HISTORY_PAGE_SIZE + '&offset=' + offset,
          { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 401) throw new Error('Sign in to see your search history.');
        if (!r.ok) throw new Error('History is unavailable right now. Please try again.');
        return r.json();
      })
      .then(function (data) {
        if (seq !== historyState.seq) return;
        var incoming = data && Array.isArray(data.items) ? data.items : [];
        if (append) historyState.items = historyState.items.concat(incoming);
        else historyState.items = incoming;
        historyState.total = data && typeof data.total === 'number'
          ? data.total : historyState.items.length;
        historyState.hasMore = !!(data && data.has_more);
        historyState.loadedAt = Date.now();
        renderHistoryItems();
        historyStatus.textContent = historyState.items.length
          ? 'Showing ' + historyState.items.length + ' of ' + historyState.total +
            ' saved searches.'
          : 'No search history yet.';
      })
      .catch(function (err) {
        if (seq !== historyState.seq) return;
        var message = err && err.message ? err.message : 'History could not be loaded.';
        if (!append) {
          historyState.items = [];
          historyState.total = 0;
          historyState.hasMore = false;
          historyList.replaceChildren();
          historyEmpty.textContent = message;
          historyEmpty.classList.remove('hidden');
          historySummary.textContent = HISTORY_DEFAULT_SUMMARY;
          updateHistoryFooter();
        }
        historyStatus.textContent = message;
      })
      .finally(function () {
        if (seq !== historyState.seq) return;
        historyState.loading = false;
        historyList.removeAttribute('aria-busy');
        updateHistoryFooter();
      });
  }

  function clearAllHistory() {
    if (!currentUser || !historyClearConfirm) return;
    historyClearConfirm.disabled = true;
    historyClearConfirm.textContent = 'Deleting…';

    fetch('/api/history', { method: 'DELETE', credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('Could not clear history. Please try again.');
      })
      .then(function () {
        historyState.items = [];
        historyState.total = 0;
        historyState.hasMore = false;
        historyState.seq += 1;
        recentHistoryCache = { items: [], at: Date.now() };
        historyList.replaceChildren();
        historyEmpty.textContent = HISTORY_EMPTY_TEXT;
        historyEmpty.classList.remove('hidden');
        historySummary.textContent = HISTORY_DEFAULT_SUMMARY;
        historyStatus.textContent = 'Search history cleared.';
        if (suggestState.kind === 'history') closeSuggestions();
        hideHistoryConfirm();
      })
      .catch(function (err) {
        historyStatus.textContent = err && err.message
          ? err.message : 'Could not clear history. Please try again.';
      })
      .finally(function () {
        historyClearConfirm.disabled = false;
        historyClearConfirm.textContent = 'Delete all';
      });
  }

  if (historyClose) {
    historyClose.addEventListener('click', closeHistory);
  }
  if (historyDialog) {
    historyDialog.addEventListener('click', function (e) {
      // The backdrop and the dialog itself share a target. Only close when
      // the click is actually outside the dialog box, so clicking its padding
      // does nothing and keyboard activation is never mistaken for a backdrop
      // click.
      if (e.target !== historyDialog) return;
      var rect = historyDialog.getBoundingClientRect();
      var outside = e.clientX < rect.left || e.clientX > rect.right ||
                    e.clientY < rect.top || e.clientY > rect.bottom;
      if (outside) closeHistory();
    });
    historyDialog.addEventListener('close', function () {
      historyState.seq += 1;
      historyState.loading = false;
      hideHistoryConfirm();
      historyStatus.textContent = '';
    });
    historyDialog.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      // Dismiss the delete confirmation first, then the whole dialog.
      if (historyConfirm && !historyConfirm.classList.contains('hidden')) {
        hideHistoryConfirm();
        if (historyClear) historyClear.focus();
        return;
      }
      closeHistory();
    });
  }
  if (historyLoadMore) {
    historyLoadMore.addEventListener('click', function () { loadHistory(true); });
  }
  if (historyClear) {
    historyClear.addEventListener('click', showHistoryConfirm);
  }
  if (historyClearCancel) {
    historyClearCancel.addEventListener('click', function () {
      hideHistoryConfirm();
      if (historyClear) historyClear.focus();
    });
  }
  if (historyClearConfirm) {
    historyClearConfirm.addEventListener('click', clearAllHistory);
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
      var then = new Date(dateStr).getTime();
      if (!isFinite(then)) return '';
      var diff = Math.max(0, Date.now() - then);
      var mins  = Math.floor(diff / 60000);
      var hours = Math.floor(diff / 3600000);
      var days  = Math.floor(diff / 86400000);
      if (mins  < 1)   return 'just now';
      if (mins  < 60)  return mins  + ' minute'  + (mins  !== 1 ? 's' : '') + ' ago';
      if (hours < 24)  return hours + ' hour'    + (hours !== 1 ? 's' : '') + ' ago';
      if (days  < 30)  return days  + ' day'     + (days  !== 1 ? 's' : '') + ' ago';
      if (days  < 365) {
        var months = Math.floor(days / 30);
        return months + ' month' + (months !== 1 ? 's' : '') + ' ago';
      }
      var years = Math.floor(days / 365);
      return years + ' year' + (years !== 1 ? 's' : '') + ' ago';
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

  // ---------- Search-engine hint ----------
  (function initEngineBanner() {
    if (!engineBanner) return;
    var dismissed = false;
    try { dismissed = window.localStorage.getItem(ENGINE_HINT_KEY) === '1'; } catch (e) {}
    if (!dismissed && !document.body.classList.contains('searching')) {
      engineBanner.classList.remove('hidden');
    }
    if (engineBannerClose) {
      engineBannerClose.addEventListener('click', function () {
        engineBanner.classList.add('hidden');
        try { window.localStorage.setItem(ENGINE_HINT_KEY, '1'); } catch (e) {}
      });
    }
  })();

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
  } else if (window.EightSearchNews && window.EightSearchNews.load) {
    window.EightSearchNews.load();
  }

  window.EightSearch = {
    showLoginBanner: showLoginBanner,
    setMode: setMode
  };
})();
