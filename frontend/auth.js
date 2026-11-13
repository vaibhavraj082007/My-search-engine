/* 8search – shared auth interactions */
(function () {
  'use strict';

  document.querySelectorAll('.auth-reveal').forEach(function (button) {
    button.addEventListener('click', function () {
      var input = button.parentElement.querySelector('input');
      if (!input) return;

      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.classList.toggle('is-visible', show);
      button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    });
  });
})();
