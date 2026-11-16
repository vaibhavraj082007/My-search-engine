/**
 * 8search – Trending News Client (news.js)
 * Fetches server-aggregated news from /api/news, renders category cards,
 * and handles story preview modals.
 */

(function () {
  'use strict';

  var currentCategory = 'all';
  var listEl = document.getElementById('tnList');
  var updatedEl = document.getElementById('tnUpdated');
  var statusEl = document.getElementById('tnStatus');
  var chipsEl = document.getElementById('tnChips');
  var modalEl = document.getElementById('tnModal');
  var modalClose = document.getElementById('tnModalClose');
  var modalDone = document.getElementById('tnModalDone');
  var modalBackdrop = document.getElementById('tnModalBackdrop');
  var modalTitle = document.getElementById('tnModalTitle');
  var modalSummary = document.getElementById('tnModalSummary');
  var modalMeta = document.getElementById('tnModalMeta');
  var modalMedia = document.getElementById('tnModalMedia');
  var modalLink = document.getElementById('tnModalLink');

  if (!listEl) return;

  function esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function relativeTime(isoString) {
    if (!isoString) return '';
    var date = new Date(isoString);
    var now = new Date();
    var diffMs = now - date;
    var diffSec = Math.floor(diffMs / 1000);
    var diffMin = Math.floor(diffSec / 60);
    var diffHr = Math.floor(diffMin / 60);
    var diffDay = Math.floor(diffHr / 24);

    if (diffSec < 60) return 'Just now';
    if (diffMin < 60) return diffMin + 'm ago';
    if (diffHr < 24) return diffHr + 'h ago';
    if (diffDay < 7) return diffDay + 'd ago';
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function openStory(item) {
    if (!modalEl) return;
    if (modalTitle) modalTitle.textContent = item.title || '';
    if (modalSummary) modalSummary.textContent = item.summary || item.snippet || '';
    if (modalMeta) {
      var source = item.source || item.publisher || 'News';
      var time = relativeTime(item.published_at || item.published || item.created_at);
      modalMeta.textContent = [source, time].filter(Boolean).join(' · ');
    }
    if (modalMedia) {
      if (item.image_url || item.image) {
        modalMedia.innerHTML = '<img src="' + esc(item.image_url || item.image) + '" alt="" loading="lazy" onerror="this.parentElement.style.display=\'none\'">';
        modalMedia.style.display = '';
      } else {
        modalMedia.innerHTML = '';
        modalMedia.style.display = 'none';
      }
    }
    if (modalLink) {
      modalLink.href = item.url || '#';
      modalLink.textContent = 'Read full article on ' + (item.source || item.publisher || 'publisher website') + ' →';
    }
    modalEl.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeStory() {
    if (!modalEl) return;
    modalEl.classList.add('hidden');
    document.body.style.overflow = '';
  }

  if (modalClose) modalClose.addEventListener('click', closeStory);
  if (modalDone) modalDone.addEventListener('click', closeStory);
  if (modalBackdrop) modalBackdrop.addEventListener('click', closeStory);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modalEl && !modalEl.classList.contains('hidden')) {
      closeStory();
    }
  });

  function renderNews(items) {
    listEl.replaceChildren();
    if (!items || !items.length) {
      if (statusEl) statusEl.textContent = 'No news available for this category right now.';
      listEl.setAttribute('aria-busy', 'false');
      return;
    }
    if (statusEl) statusEl.textContent = '';

    items.forEach(function (item) {
      var card = document.createElement('article');
      card.className = 'tn-card';
      card.tabIndex = 0;

      var imgHtml = '';
      if (item.image_url || item.image) {
        imgHtml = '<div class="tn-card-thumb"><img src="' + esc(item.image_url || item.image) + '" alt="" loading="lazy" onerror="this.parentElement.style.display=\'none\'"></div>';
      }

      var source = item.source || item.publisher || 'News';
      var time = relativeTime(item.published_at || item.published || item.created_at);

      card.innerHTML =
        imgHtml +
        '<div class="tn-card-content">' +
          '<div class="tn-card-meta">' + esc(source) + (time ? ' · ' + esc(time) : '') + '</div>' +
          '<h3 class="tn-card-title">' + esc(item.title || '') + '</h3>' +
          (item.summary ? '<p class="tn-card-snippet">' + esc(item.summary) + '</p>' : '') +
        '</div>';

      card.addEventListener('click', function () {
        openStory(item);
      });
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') openStory(item);
      });

      listEl.appendChild(card);
    });
    listEl.setAttribute('aria-busy', 'false');
  }

  function loadNews(category) {
    if (category) currentCategory = category;
    listEl.setAttribute('aria-busy', 'true');
    if (statusEl) statusEl.textContent = 'Loading stories…';

    fetch('/api/news?category=' + encodeURIComponent(currentCategory))
      .then(function (res) {
        if (!res.ok) throw new Error('Failed to load news');
        return res.json();
      })
      .then(function (data) {
        if (updatedEl && data.updated_at) {
          updatedEl.textContent = 'Updated ' + relativeTime(data.updated_at);
        }
        renderNews(data.items || []);
      })
      .catch(function () {
        if (statusEl) statusEl.textContent = 'Trending news is temporarily unavailable.';
        listEl.setAttribute('aria-busy', 'false');
      });
  }

  if (chipsEl) {
    chipsEl.addEventListener('click', function (e) {
      var chip = e.target.closest('.tn-chip');
      if (!chip) return;
      var cat = chip.getAttribute('data-category');
      if (!cat) return;

      chipsEl.querySelectorAll('.tn-chip').forEach(function (c) {
        c.classList.remove('active');
        c.setAttribute('aria-selected', 'false');
      });
      chip.classList.add('active');
      chip.setAttribute('aria-selected', 'true');
      loadNews(cat);
    });
  }

  window.EightSearchNews = {
    load: loadNews,
    open: openStory,
    close: closeStory
  };

  // Initial load
  loadNews('all');
})();
