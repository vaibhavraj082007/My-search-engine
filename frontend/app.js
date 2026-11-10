/* =========================================================
   8search – Core Application Logic (app.js)
   ========================================================= */

(function () {
  'use strict';

  // ---------- DOM refs ----------
  var searchForm = document.getElementById('searchForm');
  var searchInput = document.getElementById('searchInput');
  var searchSection = document.getElementById('searchSection');
  var resultsSection = document.getElementById('resultsSection');
  var resultsContainer = document.getElementById('resultsContainer');
  var pagination = document.getElementById('pagination');
  var userArea = document.getElementById('userArea');
  var loginBanner = document.getElementById('loginBanner');
  var bannerDismiss = document.getElementById('bannerDismiss');
  var luckyBtn = document.getElementById('luckyBtn');
  var utcClock = document.getElementById('utcClock');

  var currentUser = null;
  var currentQuery = '';
  var currentPage = 1;

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
      .then(function (r) {
        if (!r.ok) throw new Error('not logged in');
        return r.json();
      })
      .then(function (data) {
        currentUser = data.email;
        renderUserArea();
      })
      .catch(function () {
        currentUser = null;
        renderUserArea();
      });
  }

  function renderUserArea() {
    if (currentUser) {
      userArea.innerHTML =
        '<div class="user-info">' +
          '<span class="user-email">' + escapeHTML(currentUser) + '</span>' +
          '<button class="logout-btn" id="logoutBtn">Sign out</button>' +
        '</div>';
      document.getElementById('logoutBtn').addEventListener('click', handleLogout);
    } else {
      userArea.innerHTML = '<a href="login.html" class="sign-in-link">Sign in</a>';
    }
  }

  function handleLogout() {
    fetch('/api/logout', { method: 'POST', credentials: 'same-origin' })
      .then(function () {
        currentUser = null;
        localStorage.removeItem('guestSearchCount');
        renderUserArea();
      })
      .catch(function () {
        currentUser = null;
        renderUserArea();
      });
  }

  // ---------- Guest search tracking ----------
  function getGuestSearchCount() {
    return parseInt(localStorage.getItem('guestSearchCount') || '0', 10);
  }

  function incrementGuestSearchCount() {
    var count = getGuestSearchCount() + 1;
    localStorage.setItem('guestSearchCount', String(count));
    return count;
  }

  // ---------- Search ----------
  searchForm.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = searchInput.value.trim();
    if (!q) return;

    // URL detection: contains "." and no spaces → navigate
    if (q.indexOf('.') !== -1 && q.indexOf(' ') === -1) {
      var url = q;
      if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
      window.location.href = url;
      return;
    }

    currentQuery = q;
    currentPage = 1;
    performSearch(q, 1);
  });

  luckyBtn.addEventListener('click', function () {
    var q = searchInput.value.trim();
    if (!q) return;
    if (q.indexOf('.') !== -1 && q.indexOf(' ') === -1) {
      var url = q;
      if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
      window.location.href = url;
      return;
    }
    currentQuery = q;
    currentPage = 1;
    performSearch(q, 1, true);
  });

  function performSearch(query, page, lucky) {
    // compact the search section
    searchSection.classList.add('compact');

    var url = '/api/search?q=' + encodeURIComponent(query) + '&page=' + page;
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        // track guest searches
        if (!currentUser) {
          incrementGuestSearchCount();
        }

        if (data.redirect) {
          window.location.href = data.redirect;
          return;
        }

        if (data.limit_reached) {
          showLoginBanner();
        }

        if (lucky && data.results && data.results.length > 0) {
          window.location.href = data.results[0].url;
          return;
        }

        renderResults(data);
      })
      .catch(function (err) {
        resultsContainer.innerHTML =
          '<div class="no-results">Something went wrong. Please try again.</div>';
        resultsSection.classList.remove('hidden');
      });
  }

  function renderResults(data) {
    resultsSection.classList.remove('hidden');

    if (!data.results || data.results.length === 0) {
      resultsContainer.innerHTML =
        '<div class="no-results">No results found for "<strong>' +
        escapeHTML(currentQuery) + '</strong>"</div>';
      pagination.innerHTML = '';
      return;
    }

    var html = '';
    for (var i = 0; i < data.results.length; i++) {
      var r = data.results[i];
      var displayUrl = r.url.replace(/^https?:\/\//, '').replace(/\/$/, '');
      html +=
        '<div class="result-item">' +
          '<div class="result-url">' + escapeHTML(displayUrl) + '</div>' +
          '<div class="result-title"><a href="' + escapeAttr(r.url) + '" target="_blank" rel="noopener">' +
            escapeHTML(r.title) + '</a></div>' +
          '<div class="result-snippet">' + escapeHTML(r.snippet) + '</div>' +
        '</div>';
    }
    resultsContainer.innerHTML = html;

    // Pagination
    if (data.total) {
      var perPage = 10;
      var totalPages = Math.ceil(data.total / perPage);
      renderPagination(data.page || currentPage, totalPages);
    } else {
      pagination.innerHTML = '';
    }

    // Scroll to results
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderPagination(current, total) {
    if (total <= 1) { pagination.innerHTML = ''; return; }

    var html = '';
    if (current > 1) {
      html += '<button class="page-btn" data-page="' + (current - 1) + '">&laquo; Prev</button>';
    }

    var start = Math.max(1, current - 4);
    var end = Math.min(total, current + 4);

    for (var p = start; p <= end; p++) {
      html += '<button class="page-btn' + (p === current ? ' active' : '') +
        '" data-page="' + p + '">' + p + '</button>';
    }

    if (current < total) {
      html += '<button class="page-btn" data-page="' + (current + 1) + '">Next &raquo;</button>';
    }

    pagination.innerHTML = html;
    pagination.querySelectorAll('.page-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var page = parseInt(this.getAttribute('data-page'), 10);
        currentPage = page;
        performSearch(currentQuery, page);
      });
    });
  }

  // ---------- Login Banner ----------
  function showLoginBanner() {
    loginBanner.classList.remove('hidden');
  }

  bannerDismiss.addEventListener('click', function () {
    loginBanner.classList.add('hidden');
  });

  // ---------- Helpers ----------
  function escapeHTML(str) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function escapeAttr(str) {
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
              .replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ---------- Init ----------
  checkAuth();

  // Expose for map.js
  window.EightSearch = {
    showLoginBanner: showLoginBanner
  };
})();
