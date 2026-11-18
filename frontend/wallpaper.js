/* 8search Wallpaper Customizer
 * 20+ Presets across genres + custom image upload from device.
 * Persists in localStorage. Zero server load.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "8search_custom_bg";
  var PRESET_KEY = "8search_bg_preset";

  var PRESETS = {
    // Nature
    aurora: "https://images.unsplash.com/photo-1531366936337-7c912a4589a7?auto=format&fit=crop&w=2000&q=80",
    alpine: "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=2000&q=80",
    forest: "https://images.unsplash.com/photo-1448375240586-882707db888b?auto=format&fit=crop&w=2000&q=80",
    ocean: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=2000&q=80",
    autumn: "https://images.unsplash.com/photo-1476820865390-c52aeebb9891?auto=format&fit=crop&w=2000&q=80",
    desert: "https://images.unsplash.com/photo-1509316975850-ff9c5deb0cd9?auto=format&fit=crop&w=2000&q=80",
    waterfall: "https://images.unsplash.com/photo-1432405972618-c60b0225b8f9?auto=format&fit=crop&w=2000&q=80",
    // Space
    galaxy: "https://images.unsplash.com/photo-1506703719100-a0f3a48c0f86?auto=format&fit=crop&w=2000&q=80",
    moon: "https://images.unsplash.com/photo-1614728894747-a83421e2b9c9?auto=format&fit=crop&w=2000&q=80",
    nebula: "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=2000&q=80",
    starlit: "https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=2000&q=80",
    // City
    tokyo: "https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=2000&q=80",
    nyc: "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?auto=format&fit=crop&w=2000&q=80",
    cyberpunk: "https://images.unsplash.com/photo-1514565131-fce0801e5785?auto=format&fit=crop&w=2000&q=80",
    bridge: "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?auto=format&fit=crop&w=2000&q=80",
    // Abstract
    emerald: "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=2000&q=80",
    obsidian: "https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=2000&q=80",
    pastel: "https://images.unsplash.com/photo-1557683316-973673baf926?auto=format&fit=crop&w=2000&q=80",
    // Art
    sakura: "https://images.unsplash.com/photo-1522383225653-ed111181a951?auto=format&fit=crop&w=2000&q=80",
    sunset_clouds: "https://images.unsplash.com/photo-1495616811223-4d98c6e9c869?auto=format&fit=crop&w=2000&q=80"
  };

  var DEFAULT_PRESET = "nyc";

  var bgToggleBtn = document.getElementById("bgToggleBtn");
  var bgDialog = document.getElementById("bgDialog");
  var bgDialogClose = document.getElementById("bgDialogClose");
  var bgPresetsGrid = document.getElementById("bgPresetsGrid");
  var bgGenreChips = document.getElementById("bgGenreChips");
  var customBgFileInput = document.getElementById("customBgFileInput");
  var customBgUploadBtn = document.getElementById("customBgUploadBtn");
  var customBgResetBtn = document.getElementById("customBgResetBtn");
  var bgFixedLayer = document.getElementById("bgFixedLayer");

  function applyWallpaper(url, presetName) {
    if (!bgFixedLayer) bgFixedLayer = document.getElementById("bgFixedLayer");
    if (!url) {
      document.body.classList.remove("has-custom-bg");
      document.body.style.backgroundImage = "";
      if (bgFixedLayer) bgFixedLayer.style.backgroundImage = "";
      try {
        localStorage.setItem(PRESET_KEY, "classic");
        localStorage.removeItem(STORAGE_KEY);
      } catch (e) {}
      updateActiveCard("default");
      return;
    }

    document.body.classList.add("has-custom-bg");
    var bgCss = "url('" + url.replace(/'/g, "\\'") + "')";
    if (bgFixedLayer) {
      bgFixedLayer.style.backgroundImage = bgCss;
      document.body.style.backgroundImage = "";
    } else {
      document.body.style.backgroundImage = bgCss;
    }
    try {
      localStorage.setItem(STORAGE_KEY, url);
      if (presetName) localStorage.setItem(PRESET_KEY, presetName);
      else localStorage.removeItem(PRESET_KEY);
    } catch (e) {}
    updateActiveCard(presetName || "custom");
  }

  function updateActiveCard(activeKey) {
    if (!bgPresetsGrid) return;
    var cards = bgPresetsGrid.querySelectorAll(".bg-preset-card");
    cards.forEach(function (card) {
      var key = card.getAttribute("data-bg");
      card.classList.toggle("active", key === activeKey);
    });
  }

  // Restore saved on startup, or default to New York
  try {
    var savedBg = localStorage.getItem(STORAGE_KEY);
    var savedPreset = localStorage.getItem(PRESET_KEY);
    if (savedPreset === "classic") {
      applyWallpaper(null, "classic");
    } else if (savedBg) {
      applyWallpaper(savedBg, savedPreset);
    } else if (savedPreset && PRESETS[savedPreset]) {
      applyWallpaper(PRESETS[savedPreset], savedPreset);
    } else {
      // Default wallpaper for everyone: New York City
      applyWallpaper(PRESETS[DEFAULT_PRESET], DEFAULT_PRESET);
    }
  } catch (e) {
    applyWallpaper(PRESETS[DEFAULT_PRESET], DEFAULT_PRESET);
  }

  // Open / close dialog
  function openBgDialog() {
    if (!bgDialog) return;
    var currentPreset = null;
    try {
      currentPreset = localStorage.getItem(PRESET_KEY);
      if (currentPreset === "classic") {
        currentPreset = "default";
      } else if (!currentPreset && !localStorage.getItem(STORAGE_KEY)) {
        currentPreset = DEFAULT_PRESET;
      }
    } catch (e) {
      currentPreset = DEFAULT_PRESET;
    }
    updateActiveCard(currentPreset || "custom");

    if (typeof bgDialog.showModal === "function") {
      bgDialog.showModal();
    } else {
      bgDialog.setAttribute("open", "");
    }
  }

  function closeBgDialog() {
    if (!bgDialog) return;
    if (typeof bgDialog.close === "function") {
      bgDialog.close();
    } else {
      bgDialog.removeAttribute("open");
    }
  }

  if (bgToggleBtn) {
    bgToggleBtn.addEventListener("click", openBgDialog);
  }

  if (bgDialogClose) {
    bgDialogClose.addEventListener("click", closeBgDialog);
  }

  if (bgDialog) {
    bgDialog.addEventListener("click", function (e) {
      if (e.target === bgDialog) closeBgDialog();
    });
  }

  // Genre filtering
  if (bgGenreChips && bgPresetsGrid) {
    bgGenreChips.addEventListener("click", function (e) {
      var chip = e.target.closest(".bg-genre-chip");
      if (!chip) return;
      var genre = chip.getAttribute("data-genre");

      bgGenreChips.querySelectorAll(".bg-genre-chip").forEach(function (c) {
        c.classList.toggle("active", c === chip);
      });

      var cards = bgPresetsGrid.querySelectorAll(".bg-preset-card");
      cards.forEach(function (card) {
        if (genre === "all") {
          card.style.display = "";
        } else {
          var cardGenre = card.getAttribute("data-genre");
          card.style.display = (cardGenre === genre || card.getAttribute("data-bg") === "default") ? "" : "none";
        }
      });
    });
  }

  // Presets selection
  if (bgPresetsGrid) {
    bgPresetsGrid.addEventListener("click", function (e) {
      var card = e.target.closest(".bg-preset-card");
      if (!card) return;
      var bgKey = card.getAttribute("data-bg");
      if (bgKey === "default") {
        applyWallpaper(null, "classic");
      } else if (PRESETS[bgKey]) {
        applyWallpaper(PRESETS[bgKey], bgKey);
      }
    });
  }

  // File upload
  if (customBgUploadBtn && customBgFileInput) {
    customBgUploadBtn.addEventListener("click", function () {
      customBgFileInput.click();
    });

    customBgFileInput.addEventListener("change", function () {
      var file = customBgFileInput.files && customBgFileInput.files[0];
      if (!file) return;

      var reader = new FileReader();
      reader.onload = function (evt) {
        var img = new Image();
        img.onload = function () {
          var maxDim = 1920;
          var w = img.width;
          var h = img.height;
          if (w > maxDim || h > maxDim) {
            if (w > h) {
              h = Math.round((h * maxDim) / w);
              w = maxDim;
            } else {
              w = Math.round((w * maxDim) / h);
              h = maxDim;
            }
          }
          var canvas = document.createElement("canvas");
          canvas.width = w;
          canvas.height = h;
          var ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0, w, h);
          var dataUrl = canvas.toDataURL("image/jpeg", 0.86);
          applyWallpaper(dataUrl, null);
        };
        img.src = evt.target.result;
      };
      reader.readAsDataURL(file);
      customBgFileInput.value = "";
    });
  }

  // Reset to classic (no wallpaper)
  if (customBgResetBtn) {
    customBgResetBtn.addEventListener("click", function () {
      applyWallpaper(null, "classic");
    });
  }
})();
