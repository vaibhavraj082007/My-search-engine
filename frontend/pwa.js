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
  var macWeblocBtn = document.getElementById("macWeblocBtn");
  var winUrlBtn = document.getElementById("winUrlBtn");
  var macDmgBtn = document.getElementById("macDmgBtn");
  var winExeBtn = document.getElementById("winExeBtn");
  var androidApkBtn = document.getElementById("androidApkBtn");
  var androidPwaBtn = document.getElementById("androidPwaBtn");
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
      label: "Install 8search to iPhone / iPad",
      note: "In Safari: Tap Share (↑) → Add to Home Screen (⊕) → Add"
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
      directInstallBtn.setAttribute("download", info.filename);
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

  // Client-side lightweight shortcut generators
  function downloadWebloc() {
    var origin = window.location.origin;
    var content =
      '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n' +
      '<plist version="1.0">\n' +
      '<dict>\n' +
      '\t<key>URL</key>\n' +
      '\t<string>' + origin + '/</string>\n' +
      '</dict>\n' +
      '</plist>\n';
    var blob = new Blob([content], { type: "application/x-apple-binary" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "8search.webloc";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 1000);
  }

  function downloadUrlShortcut() {
    var origin = window.location.origin;
    var content =
      "[InternetShortcut]\r\n" +
      "URL=" + origin + "/\r\n" +
      "IconIndex=0\r\n";
    var blob = new Blob([content], { type: "text/plain" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "8search.url";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 1000);
  }

  // Wiring buttons
  if (macWeblocBtn) {
    macWeblocBtn.addEventListener("click", function (e) {
      e.preventDefault();
      downloadWebloc();
    });
  }

  if (winUrlBtn) {
    winUrlBtn.addEventListener("click", function (e) {
      e.preventDefault();
      downloadUrlShortcut();
    });
  }

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

  if (androidPwaBtn) {
    androidPwaBtn.addEventListener("click", function (e) {
      e.preventDefault();
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt = null;
      } else {
        downloadDirect("android");
      }
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
