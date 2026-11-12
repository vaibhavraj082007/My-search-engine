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
  function goHome() {
    searchSection.classList.remove('compact');
    resultsSection.classList.add('hidden');
    resultsContainer.innerHTML = '';
    pagination.innerHTML = '';
    if (globeSection) globeSection.style.display = '';
    searchInput.value = '';
    currentQuery = '';
    currentPage  = 1;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  var logo = document.querySelector('.top-bar-logo');
  if (logo) logo.addEventListener('click', function (e) { e.preventDefault(); goHome(); });

  // ---------- Search submit ----------
  searchForm.addEventListener('submit', function (e) {
    e.preventDefault();
    doSearch(searchInput.value.trim());
  });

  if (luckyBtn) luckyBtn.addEventListener('click', function () {
    doSearch(searchInput.value.trim(), true);
  });

  function doSearch(q, lucky) {
    if (!q) return;
    // URL-like → navigate
    if (q.indexOf('.') !== -1 && q.indexOf(' ') === -1) {
      window.location.href = /^https?:\/\//i.test(q) ? q : 'https://' + q;
      return;
    }
    currentQuery = q;
    currentPage  = 1;
    performSearch(q, 1, lucky);
  }

  // ---------- Search ----------
  function performSearch(query, page, lucky) {
    // Switch to results layout
    searchSection.classList.add('compact');
    if (globeSection) globeSection.style.display = 'none';
    resultsSection.classList.remove('hidden');

    resultsContainer.innerHTML =
      '<div class="search-loading"><div class="spinner"></div><p>Searching…</p></div>';
    pagination.innerHTML = '';

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

        renderResults(data);
      })
      .catch(function (err) {
        resultsContainer.innerHTML =
          '<div class="no-results"><div class="no-results-icon">⚠️</div>' +
          '<h3>Something went wrong</h3><p>' +
          esc(err && err.message ? err.message : 'Check your connection and try again.') +
          '</p></div>';
      });
  }

  // ---------- Render results ----------
  function renderResults(data) {
    var results = data.results || [];
    var news    = data.news    || [];
    var answer  = data.answer  || null;
    var wiki    = data.wikipedia || null;
    var videos  = data.videos  || [];

    if (!results.length && !news.length && !answer && !wiki && !videos.length) {
      resultsContainer.innerHTML =
        '<div class="no-results"><div class="no-results-icon">🔍</div>' +
        '<h3>No results found</h3><p>Try different keywords for "<strong>' +
        esc(currentQuery) + '</strong>".</p></div>';
      pagination.innerHTML = '';
      return;
    }

    var html = '';

    // ── Results count bar ──
    html += '<div class="results-info">About <strong>' + (data.total || results.length) +
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

    // Pagination (simple prev/next only – DDG doesn't expose total count)
    renderPagination(currentPage);
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
        '</div>' +
        '<a class="result-title" href="' + escAttr(r.url) + '" target="_blank" rel="noopener">' +
          esc(r.title || 'Untitled') +
        '</a>' +
        '<div class="result-snippet">' + esc(r.snippet || '') + '</div>' +
      '</div>'
    );
  }

  // ---------- Pagination ----------
  function renderPagination(current) {
    var html = '';
    if (current > 1)
      html += '<button class="page-btn" data-page="' + (current - 1) + '">&laquo; Prev</button>';
    html += '<button class="page-btn active">' + current + '</button>';
    html += '<button class="page-btn" data-page="' + (current + 1) + '">Next &raquo;</button>';
    pagination.innerHTML = html;
    pagination.querySelectorAll('.page-btn[data-page]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        currentPage = parseInt(this.dataset.page, 10);
        performSearch(currentQuery, currentPage);
      });
    });
  }

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
  checkAuth();
  window.EightSearch = { showLoginBanner: showLoginBanner };
})();
