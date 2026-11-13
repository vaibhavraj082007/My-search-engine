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

  var currentUser  = null;
  var currentQuery = '';
  var currentPage  = 1;
  var searchSeq    = 0;
  var PAGE_WINDOW  = 5;
  var MAX_PAGE     = 10;

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

  // ---------- Auth ----------
  function checkAuth() {
    fetch('/api/me', { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (d) { currentUser = d.email; renderUserArea(); })
      .catch(function () { currentUser = null; renderUserArea(); });
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

  // ---------- Home ----------
  function goHome(pushHistory) {
    searchSection.classList.remove('compact');
    resultsSection.classList.add('hidden');
    resultsContainer.innerHTML = '';
    pagination.innerHTML = '';
    if (globeSection) globeSection.style.display = '';
    searchInput.value = '';
    currentQuery = '';
    currentPage  = 1;
    searchSeq    = 0;

    if (pushHistory !== false) {
      try { window.history.pushState({}, '', window.location.pathname); } catch (e) {}
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  var logo = document.querySelector('.top-bar-logo');
  if (logo) logo.addEventListener('click', function (e) { e.preventDefault(); goHome(); });

  // ---------- Search submit ----------
  searchForm.addEventListener('submit', function (e) {
    e.preventDefault();
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
        searchInput.placeholder = 'Discover the exceptional...';
      };
      recognition.onend = function () {
        micBtn.classList.remove('listening');
        searchInput.placeholder = 'Discover the exceptional...';
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

  // ---------- URL / history ----------
  function readRoute() {
    try {
      var params = new URLSearchParams(window.location.search);
      var q = (params.get('q') || '').trim();
      var page = parseInt(params.get('page') || '1', 10);
      if (!isFinite(page) || page < 1) page = 1;
      if (page > MAX_PAGE) page = MAX_PAGE;
      return { q: q, page: page };
    } catch (e) {
      return { q: '', page: 1 };
    }
  }

  function updateUrl(query, page, mode) {
    try {
      var params = new URLSearchParams();
      params.set('q', query);
      if (page > 1) params.set('page', String(page));
      var url = window.location.pathname + '?' + params.toString();
      var state = { q: query, page: page };
      if (mode === 'push') window.history.pushState(state, '', url);
      else window.history.replaceState(state, '', url);
    } catch (e) {}
  }

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
    currentQuery = query;
    currentPage  = page;
    var seq = ++searchSeq;

    // Switch to results layout
    searchSection.classList.add('compact');
    if (globeSection) globeSection.style.display = 'none';
    resultsSection.classList.remove('hidden');

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

        currentPage = data.page || page;
        if (historyMode) updateUrl(query, currentPage, historyMode);
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

  // ---------- Render results ----------
  function renderResults(data) {
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
    results.forEach(function (r) { html += buildResultCard(r); });

    // ── In the news ──
    if (news.length) html += buildNewsSection(news);

    resultsContainer.innerHTML = html;
    wireAnswerToggle();
    window.scrollTo({ top: 0, behavior: 'smooth' });

    renderPagination(page, data);
  }

  function buildAnswerCard(a) {
    var kicker = a.kind === 'definition' ? 'Meaning' : 'Quick answer';
    var text   = a.text || '';
    var expandable = text.length > 240;
    var source = a.url
      ? '<a class="answer-source" href="' + escAttr(a.url) + '" target="_blank" rel="noopener">Source: ' +
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
      '<a class="wiki-card" href="' + escAttr(url) + '" target="_blank" rel="noopener">' +
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

    videos.forEach(function (v) {
      var meta = [v.channel, v.published].filter(Boolean).join(' · ');
      html +=
        '<a class="video-row" href="' + escAttr(v.url) + '" target="_blank" rel="noopener">' +
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

    news.forEach(function (n) {
      var domain = domainOf(n.url);
      var favicon = 'https://www.google.com/s2/favicons?sz=16&domain=' + encodeURIComponent(domain);
      var timeAgo = n.date ? relativeTime(n.date) : '';
      html +=
        '<a class="news-card" href="' + escAttr(n.url) + '" target="_blank" rel="noopener">' +
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

  function buildResultCard(r) {
    var domain     = domainOf(r.url);
    var breadcrumb = makeBreadcrumb(r.url);
    var favicon    = 'https://www.google.com/s2/favicons?sz=16&domain=' + encodeURIComponent(domain);

    return (
      '<div class="result-item">' +
        '<div class="result-url">' +
          '<img class="result-favicon" src="' + escAttr(favicon) + '" width="16" height="16" alt="" ' +
               'onerror="this.style.display=\'none\'">' +
          '<span class="result-breadcrumb">' + esc(breadcrumb) + '</span>' +
          (r.source ? '<span class="result-source">' + esc(r.source) + '</span>' : '') +
        '</div>' +
        '<a class="result-title" href="' + escAttr(r.url) + '" target="_blank" rel="noopener">' +
          esc(r.title || 'Untitled') +
        '</a>' +
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
    searchInput.value = route.q;
    performSearch(route.q, route.page, false, null);
  });

  checkAuth();

  var initialRoute = readRoute();
  if (initialRoute.q) {
    searchInput.value = initialRoute.q;
    performSearch(initialRoute.q, initialRoute.page, false, null);
  }

  window.EightSearch = { showLoginBanner: showLoginBanner };
})();
