/* =========================================================
   8search – Map, Cameras, Weather, Earthquakes (map.js)
   ========================================================= */

(function () {
  'use strict';

  // ---------- Weather code decoder ----------
  var WEATHER_CODES = {
    0:  { desc: 'Clear sky',              icon: '☀️' },
    1:  { desc: 'Mainly clear',           icon: '🌤️' },
    2:  { desc: 'Partly cloudy',          icon: '⛅' },
    3:  { desc: 'Overcast',               icon: '☁️' },
    45: { desc: 'Fog',                    icon: '🌫️' },
    48: { desc: 'Depositing rime fog',    icon: '🌫️' },
    51: { desc: 'Light drizzle',          icon: '🌦️' },
    53: { desc: 'Moderate drizzle',       icon: '🌦️' },
    55: { desc: 'Dense drizzle',          icon: '🌦️' },
    56: { desc: 'Light freezing drizzle', icon: '🌦️' },
    57: { desc: 'Dense freezing drizzle', icon: '🌦️' },
    61: { desc: 'Slight rain',            icon: '🌧️' },
    63: { desc: 'Moderate rain',          icon: '🌧️' },
    65: { desc: 'Heavy rain',             icon: '🌧️' },
    66: { desc: 'Light freezing rain',    icon: '🌧️' },
    67: { desc: 'Heavy freezing rain',    icon: '🌧️' },
    71: { desc: 'Slight snow',            icon: '🌨️' },
    73: { desc: 'Moderate snow',          icon: '🌨️' },
    75: { desc: 'Heavy snow',             icon: '🌨️' },
    77: { desc: 'Snow grains',            icon: '🌨️' },
    80: { desc: 'Slight rain showers',    icon: '🌧️' },
    81: { desc: 'Moderate rain showers',  icon: '🌧️' },
    82: { desc: 'Violent rain showers',   icon: '🌧️' },
    85: { desc: 'Slight snow showers',    icon: '🌨️' },
    86: { desc: 'Heavy snow showers',     icon: '🌨️' },
    95: { desc: 'Thunderstorm',           icon: '⛈️' },
    96: { desc: 'Thunderstorm with hail', icon: '⛈️' },
    99: { desc: 'Thunderstorm with hail', icon: '⛈️' }
  };

  function decodeWeather(code) {
    return WEATHER_CODES[code] || { desc: 'Unknown', icon: '❓' };
  }

  // ---------- Wind direction helper ----------
  function windDirectionLabel(deg) {
    var dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
    return dirs[Math.round(deg / 22.5) % 16];
  }

  // ---------- Tile layers ----------
  var satelliteTiles = L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    {
      attribution: '&copy; Esri',
      maxZoom: 18,
      noWrap: false
    }
  );

  var streetTiles = L.tileLayer(
    'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
      noWrap: false
    }
  );

  // ---------- Initialize map ----------
  var map = L.map('map', {
    center: [20, 0],
    zoom: 2,
    zoomControl: true,
    worldCopyJump: true,
    layers: [satelliteTiles]
  });

  var isSatellite = true;
  var isGlobe = false;
  var earthquakesVisible = false;
  var earthquakeLayer = null;

  // ---------- Camera cluster layer ----------
  var cameraCluster = L.markerClusterGroup({
    maxClusterRadius: 50,
    disableClusteringAtZoom: 12,
    spiderfyOnMaxZoom: true
  });
  map.addLayer(cameraCluster);

  var cameraMarkersMap = {};
  var cameraFetchTimeout = null;

  // ---------- Fetch cameras on moveend ----------
  function fetchCameras() {
    var bounds = map.getBounds();
    var params = new URLSearchParams({
      north: bounds.getNorth(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      west: bounds.getWest()
    });

    fetch('/api/cameras?' + params.toString(), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (cameras) {
        if (!Array.isArray(cameras)) return;

        // Track existing ids
        var newIds = {};
        cameras.forEach(function (cam) {
          newIds[cam.id] = true;
          if (cameraMarkersMap[cam.id]) return; // already on map

          var marker = L.marker([cam.lat, cam.lon], {
            icon: L.divIcon({
              className: 'camera-marker',
              iconSize: [12, 12],
              iconAnchor: [6, 6]
            })
          });

          marker.on('click', function (e) {
            L.DomEvent.stopPropagation(e);
            openCameraPanel(cam);
          });

          cameraCluster.addLayer(marker);
          cameraMarkersMap[cam.id] = marker;
        });
      })
      .catch(function () { /* silently ignore */ });
  }

  map.on('moveend', function () {
    clearTimeout(cameraFetchTimeout);
    cameraFetchTimeout = setTimeout(fetchCameras, 300);
  });

  // Initial load
  fetchCameras();

  // ---------- Camera Panel ----------
  var cameraPanel = document.getElementById('cameraPanel');
  var cameraContent = document.getElementById('cameraContent');
  var cameraCloseBtn = document.getElementById('cameraClose');

  cameraCloseBtn.addEventListener('click', closeCameraPanel);

  function openCameraPanel(cam) {
    closeWeatherPanel();

    var mediaHTML = '';
    if (cam.type === 'video') {
      mediaHTML = '<video src="' + escapeAttr(cam.url) + '" autoplay muted loop playsinline controls></video>';
    } else {
      mediaHTML = '<img src="' + escapeAttr(cam.url) + '" alt="' + escapeAttr(cam.name) + '" loading="lazy">';
    }

    var html =
      mediaHTML +
      '<div class="camera-name">' + escapeHTML(cam.name) + '</div>' +
      '<div class="camera-meta">📍 ' + cam.lat.toFixed(4) + ', ' + cam.lon.toFixed(4) + '</div>' +
      (cam.source ? '<div class="camera-meta">Source: ' + escapeHTML(cam.source) + '</div>' : '') +
      (cam.credit ? '<div class="camera-meta">Credit: ' + escapeHTML(cam.credit) + '</div>' : '') +
      '<div class="camera-weather"><div class="weather-loading">Loading weather…</div></div>';

    cameraContent.innerHTML = html;
    cameraPanel.classList.remove('hidden');
    requestAnimationFrame(function () {
      cameraPanel.classList.add('show');
    });

    // Fetch weather for camera location
    fetchWeatherForPanel(cam.lat, cam.lon, cameraContent.querySelector('.camera-weather'));
  }

  function closeCameraPanel() {
    cameraPanel.classList.remove('show');
    setTimeout(function () {
      cameraPanel.classList.add('hidden');
    }, 350);
  }

  // ---------- Weather Panel ----------
  var weatherPanel = document.getElementById('weatherPanel');
  var weatherContent = document.getElementById('weatherContent');
  var weatherCloseBtn = document.getElementById('weatherClose');
  var localClockInterval = null;

  weatherCloseBtn.addEventListener('click', closeWeatherPanel);

  function openWeatherPanel(lat, lon) {
    closeCameraPanel();
    weatherContent.innerHTML = '<div class="weather-loading">Loading weather…</div>';
    weatherPanel.classList.remove('hidden');
    requestAnimationFrame(function () {
      weatherPanel.classList.add('show');
    });

    fetchWeatherForPanel(lat, lon, weatherContent, true);
  }

  function closeWeatherPanel() {
    weatherPanel.classList.remove('show');
    if (localClockInterval) {
      clearInterval(localClockInterval);
      localClockInterval = null;
    }
    setTimeout(function () {
      weatherPanel.classList.add('hidden');
    }, 350);
  }

  function fetchWeatherForPanel(lat, lon, container, isMainPanel) {
    var url = '/api/weather?lat=' + lat.toFixed(4) + '&lon=' + lon.toFixed(4);
    fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        renderWeather(data, lat, lon, container, isMainPanel);
      })
      .catch(function () {
        container.innerHTML = '<div class="weather-loading">Unable to load weather data.</div>';
      });
  }

  function renderWeather(data, lat, lon, container, isMainPanel) {
    var c = data.current;
    var w = decodeWeather(c.weather_code);
    var utcOffset = data.utc_offset_seconds || 0;

    // Clear any previous clock
    if (localClockInterval) {
      clearInterval(localClockInterval);
      localClockInterval = null;
    }

    var clockId = 'localClock_' + Date.now();

    var html =
      '<div class="weather-header">' +
        '<div class="weather-location">📍 ' + lat.toFixed(2) + '°, ' + lon.toFixed(2) + '°</div>' +
        '<div class="weather-temp-row">' +
          '<div class="weather-temp">' + Math.round(c.temperature) + '°</div>' +
          '<div>' +
            '<span class="weather-condition-icon">' + w.icon + '</span>' +
            '<span class="weather-condition">' + w.desc + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="weather-local-time">' +
          '<div>' +
            '<div class="clock-label">🕐 Local Time</div>' +
            '<div class="clock-value" id="' + clockId + '">--:--:--</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    // Details grid
    html +=
      '<div class="weather-details">' +
        '<div class="weather-detail-card">' +
          '<div class="label">💨 Wind</div>' +
          '<div class="value">' + c.wind_speed + '<span class="unit"> km/h</span></div>' +
          '<div style="margin-top:4px;">' +
            '<span class="wind-arrow" style="transform:rotate(' + (c.wind_direction || 0) + 'deg)">↑</span> ' +
            windDirectionLabel(c.wind_direction || 0) +
          '</div>' +
        '</div>' +
        '<div class="weather-detail-card">' +
          '<div class="label">🌧️ Rain</div>' +
          '<div class="value">' + (c.rain || 0) + '<span class="unit"> mm</span></div>' +
        '</div>' +
        '<div class="weather-detail-card">' +
          '<div class="label">☁️ Cloud Cover</div>' +
          '<div class="value">' + (c.cloud_cover || 0) + '<span class="unit">%</span></div>' +
        '</div>' +
        '<div class="weather-detail-card">' +
          '<div class="label">' + (c.is_day ? '☀️ Daytime' : '🌙 Nighttime') + '</div>' +
          '<div class="value">' + (c.is_day ? 'Day' : 'Night') + '</div>' +
        '</div>' +
      '</div>';

    // Forecast
    if (data.daily && data.daily.length > 0) {
      html += '<div class="weather-forecast-title">📅 Forecast</div>';
      html += '<div class="weather-forecast">';

      var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
      for (var i = 0; i < data.daily.length; i++) {
        var d = data.daily[i];
        var date = new Date(d.date + 'T00:00:00');
        var dayLabel = (i === 0) ? 'Today' : days[date.getDay()];
        var fw = decodeWeather(d.weather_code);
        var dimmed = i >= 10;
        html +=
          '<div class="forecast-card' + (dimmed ? ' dimmed' : '') + '">' +
            '<div class="fc-day">' + dayLabel + '</div>' +
            '<div class="fc-icon">' + fw.icon + '</div>' +
            '<div class="fc-high">' + Math.round(d.temp_max) + '°</div>' +
            '<div class="fc-low">' + Math.round(d.temp_min) + '°</div>' +
            (d.rain_sum > 0 ? '<div class="fc-rain">' + d.rain_sum + ' mm</div>' : '') +
          '</div>';
      }
      html += '</div>';
    }

    container.innerHTML = html;

    // Live ticking clock
    var clockEl = document.getElementById(clockId);
    if (clockEl) {
      function updateLocalClock() {
        var now = new Date();
        var utcMs = now.getTime() + now.getTimezoneOffset() * 60000;
        var localMs = utcMs + utcOffset * 1000;
        var localDate = new Date(localMs);
        var h = String(localDate.getHours()).padStart(2, '0');
        var m = String(localDate.getMinutes()).padStart(2, '0');
        var s = String(localDate.getSeconds()).padStart(2, '0');
        clockEl.textContent = h + ':' + m + ':' + s;
      }
      updateLocalClock();
      if (isMainPanel) {
        localClockInterval = setInterval(updateLocalClock, 1000);
      } else {
        setInterval(updateLocalClock, 1000);
      }
    }
  }

  // ---------- Map click → weather ----------
  map.on('click', function (e) {
    openWeatherPanel(e.latlng.lat, e.latlng.lng);
  });

  // ---------- Globe / Flat toggle ----------
  var btnGlobeFlat = document.getElementById('btnGlobeFlat');
  var mapContainer = document.getElementById('map');

  btnGlobeFlat.addEventListener('click', function () {
    isGlobe = !isGlobe;
    this.classList.toggle('active', isGlobe);

    if (isGlobe) {
      mapContainer.classList.add('globe-mode');
      map.setView([20, 0], 2, { animate: true });
    } else {
      mapContainer.classList.remove('globe-mode');
    }

    // Leaflet needs a resize nudge after shape change
    setTimeout(function () {
      map.invalidateSize();
    }, 400);
  });

  // ---------- Map / Satellite toggle ----------
  var btnMapSat = document.getElementById('btnMapSat');

  btnMapSat.addEventListener('click', function () {
    isSatellite = !isSatellite;
    this.classList.toggle('active', !isSatellite);

    if (isSatellite) {
      map.removeLayer(streetTiles);
      map.addLayer(satelliteTiles);
    } else {
      map.removeLayer(satelliteTiles);
      map.addLayer(streetTiles);
    }
  });

  // ---------- Earthquakes toggle ----------
  var btnEarthquakes = document.getElementById('btnEarthquakes');

  btnEarthquakes.addEventListener('click', function () {
    earthquakesVisible = !earthquakesVisible;
    this.classList.toggle('active', earthquakesVisible);

    if (earthquakesVisible) {
      loadEarthquakes();
    } else {
      if (earthquakeLayer) {
        map.removeLayer(earthquakeLayer);
        earthquakeLayer = null;
      }
    }
  });

  function loadEarthquakes() {
    fetch('https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (earthquakeLayer) {
          map.removeLayer(earthquakeLayer);
        }

        earthquakeLayer = L.geoJSON(data, {
          pointToLayer: function (feature, latlng) {
            var mag = feature.properties.mag || 1;
            var radius = Math.max(mag * 4, 6);
            return L.circleMarker(latlng, {
              radius: radius,
              fillColor: '#ea4335',
              color: '#ea4335',
              weight: 1.5,
              opacity: 0.8,
              fillOpacity: 0.25,
              className: 'earthquake-circle'
            });
          },
          onEachFeature: function (feature, layer) {
            var props = feature.properties;
            var mag = props.mag ? props.mag.toFixed(1) : '?';
            var place = props.place || 'Unknown location';
            var time = props.time ? new Date(props.time).toLocaleString() : '';
            layer.bindPopup(
              '<strong>M ' + mag + '</strong><br>' +
              escapeHTML(place) + '<br>' +
              '<small>' + time + '</small>'
            );
          }
        });

        if (earthquakesVisible) {
          map.addLayer(earthquakeLayer);
        }
      })
      .catch(function () { /* silently ignore */ });
  }

  // ---------- Helpers ----------
  function escapeHTML(str) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(str || ''));
    return d.innerHTML;
  }

  function escapeAttr(str) {
    return (str || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

})();
