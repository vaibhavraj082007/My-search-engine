/* Installable-app support: service worker registration, home download dialog and platform installer. */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    });
  }

  var installBtn = document.getElementById("installAppBtn");
  var installNote = document.getElementById("installAppNote");
  var homeInstallBtn = document.getElementById("homeInstallBtn");
  var downloadDialog = document.getElementById("downloadDialog");
  var downloadClose = document.getElementById("downloadClose");
  var directInstallBtn = document.getElementById("directInstallBtn");
  var directInstallLabel = document.getElementById("directInstallLabel");
  var directInstallNote = document.getElementById("directInstallNote");
  var macDmgBtn = document.getElementById("macDmgBtn");
  var winExeBtn = document.getElementById("winExeBtn");
  var androidApkBtn = document.getElementById("androidApkBtn");
  var iosProfileBtn = document.getElementById("iosProfileBtn");
  var deferredPrompt = null;

  // OS detection
  function detectOS() {
    var ua = navigator.userAgent || "";
    if (/iPhone|iPad|iPod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) {
      return "ios";
    }
    if (/Android/i.test(ua)) {
      return "android";
    }
    if (/Windows/i.test(ua)) {
      return "windows";
    }
    if (/Macintosh|Mac OS X/i.test(ua)) {
      return "mac";
    }
    return "mac";
  }

  var userOS = detectOS();
  var currentPlatform = userOS;

  var PLATFORM_FILES = {
    mac: {
      url: "/download/mac",
      filename: "8search.dmg",
      label: "Download 8search for macOS (.dmg)",
      note: "Instant direct download · Standalone app · Drag to Applications"
    },
    android: {
      url: "/download/android",
      filename: "8search.apk",
      label: "Download 8search for Android (.apk)",
      note: "Instant direct download · Standalone app · Tap to install"
    },
    windows: {
      url: "/download/windows",
      filename: "8search-Setup.exe",
      label: "Download 8search for Windows (.exe)",
      note: "Instant direct download · Standalone app · Installs Desktop & Start shortcuts"
    },
    ios: {
      url: "/download/ios",
      filename: "8search.mobileconfig",
      label: "Install 8search on iPhone / iPad (.mobileconfig)",
      note: "Tap 'Allow' on prompt → Settings → Profile Downloaded → Install"
    }
  };

  function selectPlatformTab(platform) {
    currentPlatform = platform;
    if (!downloadDialog) return;
    var tabs = downloadDialog.querySelectorAll(".download-tab");
    var panes = downloadDialog.querySelectorAll(".download-pane");

    tabs.forEach(function (tab) {
      var isTarget = tab.getAttribute("data-platform") === platform;
      tab.classList.toggle("active", isTarget);
      tab.setAttribute("aria-selected", isTarget ? "true" : "false");
    });

    panes.forEach(function (pane) {
      var isTarget = pane.id === "pane-" + platform;
      pane.classList.toggle("active", isTarget);
      pane.hidden = !isTarget;
    });

    var info = PLATFORM_FILES[platform] || PLATFORM_FILES.mac;
    if (directInstallBtn) {
      directInstallBtn.href = info.url;
      if (platform === "ios") {
        directInstallBtn.removeAttribute("download");
      } else {
        directInstallBtn.setAttribute("download", info.filename);
      }
    }
    if (directInstallLabel) {
      directInstallLabel.textContent = info.label;
    }
    if (directInstallNote) {
      directInstallNote.textContent = info.note;
    }
  }

  // Pre-select detected OS
  selectPlatformTab(userOS);

  // Tab click wiring
  if (downloadDialog) {
    downloadDialog.addEventListener("click", function (e) {
      var tab = e.target.closest(".download-tab");
      if (tab) {
        var platform = tab.getAttribute("data-platform");
        if (platform) selectPlatformTab(platform);
      }
      if (e.target === downloadDialog) {
        closeDownloadDialog();
      }
    });
  }

  function openDownloadDialog(forcedPlatform) {
    if (!downloadDialog) {
      window.location.href = "/install";
      return;
    }
    selectPlatformTab(forcedPlatform || userOS);
    if (typeof downloadDialog.showModal === "function") {
      downloadDialog.showModal();
    } else {
      downloadDialog.setAttribute("open", "");
    }
  }

  function closeDownloadDialog() {
    if (!downloadDialog) return;
    if (typeof downloadDialog.close === "function") {
      downloadDialog.close();
    } else {
      downloadDialog.removeAttribute("open");
    }
  }

  // Direct package downloader (uses forced download endpoint)
  function downloadDirect(platform) {
    var info = PLATFORM_FILES[platform] || PLATFORM_FILES.mac;
    
    if (platform === "ios") {
      window.location.href = info.url;
      if (directInstallNote) {
        directInstallNote.textContent = "Tap 'Allow' on the prompt, then open Settings → Profile Downloaded → Install.";
        directInstallNote.style.color = "#1b7a55";
        directInstallNote.style.fontWeight = "600";
      }
      return;
    }

    // Create hidden anchor pointing to /download/{platform}
    var a = document.createElement("a");
    a.href = info.url;
    a.setAttribute("download", info.filename);
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      a.remove();
    }, 1000);

    if (directInstallNote) {
      directInstallNote.textContent = "✓ " + info.filename + " download started!";
      directInstallNote.style.color = "#1b7a55";
      directInstallNote.style.fontWeight = "600";
    }
  }

  // Wiring buttons
  if (macDmgBtn) {
    macDmgBtn.addEventListener("click", function (e) {
      e.preventDefault();
      downloadDirect("mac");
    });
  }

  if (winExeBtn) {
    winExeBtn.addEventListener("click", function (e) {
      e.preventDefault();
      downloadDirect("windows");
    });
  }

  if (androidApkBtn) {
    androidApkBtn.addEventListener("click", function (e) {
      e.preventDefault();
      downloadDirect("android");
    });
  }

  if (iosProfileBtn) {
    iosProfileBtn.addEventListener("click", function (e) {
      e.preventDefault();
      downloadDirect("ios");
    });
  }

  // When clicking the main Download App button on landing screen:
  if (homeInstallBtn) {
    homeInstallBtn.addEventListener("click", function () {
      if (userOS === "ios") {
        openDownloadDialog("ios");
        downloadDirect("ios");
      } else {
        downloadDirect(userOS);
        openDownloadDialog();
      }
    });
  }

  if (downloadClose) {
    downloadClose.addEventListener("click", closeDownloadDialog);
  }

  if (directInstallBtn) {
    directInstallBtn.addEventListener("click", function (e) {
      e.preventDefault();
      if (currentPlatform === "ios") {
        downloadDirect("ios");
      } else {
        downloadDirect(currentPlatform);
        if (deferredPrompt) {
          deferredPrompt.prompt();
          deferredPrompt = null;
        }
      }
    });
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferredPrompt = event;
    if (installBtn) installBtn.classList.remove("hidden");
    if (installNote) installNote.classList.remove("hidden");
  });

  window.addEventListener("appinstalled", function () {
    deferredPrompt = null;
  });

  if (installBtn) {
    installBtn.addEventListener("click", function () {
      if (userOS === "ios") {
        openDownloadDialog("ios");
      } else {
        downloadDirect(userOS);
        openDownloadDialog();
      }
    });
  }
})();
