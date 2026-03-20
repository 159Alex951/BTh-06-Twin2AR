// Swisstopo Buildings 3D Tileset
        let buildingsSwisstopoTileset = null;
        const chkBuildingsSwisstopo = document.getElementById('chkBuildingsSwisstopo');
        async function loadBuildingsSwisstopoTileset() {
          if (buildingsSwisstopoTileset) return buildingsSwisstopoTileset;
          const tilesetUrl = 'https://3d.geo.admin.ch/ch.swisstopo.swissbuildings3d.3d/v1/tileset.json';
          buildingsSwisstopoTileset = await Cesium.Cesium3DTileset.fromUrl(tilesetUrl);
          window.viewer.scene.primitives.add(buildingsSwisstopoTileset);
          window.buildingsSwisstopoTileset = buildingsSwisstopoTileset;
          buildingsSwisstopoTileset.show = chkBuildingsSwisstopo.checked;
          return buildingsSwisstopoTileset;
        }
        if (chkBuildingsSwisstopo) {
          chkBuildingsSwisstopo.addEventListener('change', async () => {
            if (chkBuildingsSwisstopo.checked) {
              await loadBuildingsSwisstopoTileset();
              if (buildingsSwisstopoTileset) buildingsSwisstopoTileset.show = true;
            } else {
              if (buildingsSwisstopoTileset) buildingsSwisstopoTileset.show = false;
            }
          });
        }
        // start new
        let projectedBuildingsDataSource = null;
        const chkProjectedBuildings = document.getElementById('chkProjectedBuildings');

        async function loadProjectedBuildings() {
            if (projectedBuildingsDataSource) return projectedBuildingsDataSource;

            const url = "/export/projected_buildings.geojson";

            projectedBuildingsDataSource = new Cesium.GeoJsonDataSource("projected_buildings");
            await projectedBuildingsDataSource.load(url, {
                fill: Cesium.Color.ORANGE.withAlpha(0.6),
                stroke: Cesium.Color.DARKORANGE,
                strokeWidth: 2,
                clampToGround: false,
            });
            console.log(
                "Projected ds loaded",
                projectedBuildingsDataSource.entities.values.length
            );

            projectedBuildingsDataSource.entities.values.forEach(entity => {
                if (!entity.polygon) return;

                const props = entity.properties || {};

                // Prefer gastw if present (number of floors), fallback to previous height or 10 m
                const gastwProp = props.gastw;
                const gastw = gastwProp && gastwProp.getValue ? gastwProp.getValue() : gastwProp;

                const floors = (typeof gastw === "number") ? gastw : parseFloat(gastw);
                const defaultHeight = 100.0;

                const h = Number.isFinite(floors)
                    ? floors * 3.0            // 3 m per floor, tweak as needed
                    : (props.height && props.height.getValue
                        ? props.height.getValue()
                        : defaultHeight);

                entity.polygon.heightReference = Cesium.HeightReference.CLAMP_TO_GROUND;
                entity.polygon.extrudedHeight = h;
                entity.polygon.extrudedHeightReference = Cesium.HeightReference.RELATIVE_TO_GROUND;
                entity.polygon.outline = true;
                entity.polygon.outlineColor = Cesium.Color.DARKORANGE;
            });

            window.viewer.dataSources.add(projectedBuildingsDataSource);
            projectedBuildingsDataSource.show = chkProjectedBuildings.checked;
            return projectedBuildingsDataSource;
        }


        if (chkProjectedBuildings) {
            chkProjectedBuildings.addEventListener('change', async () => {
                if (chkProjectedBuildings.checked) {
                    await loadProjectedBuildings();
                    if (projectedBuildingsDataSource) projectedBuildingsDataSource.show = true;
                } else {
                    if (projectedBuildingsDataSource) projectedBuildingsDataSource.show = false;
                }
            });
        }
      // End new


      // Floating-Button für farbige Gebäude-Legende
      const bfsLegendToggle = document.getElementById('bfsLegendToggle');
      const bfsLegend = document.getElementById('bfsLegend');
      if (bfsLegendToggle && bfsLegend) {
        bfsLegendToggle.addEventListener('click', () => {
          bfsLegend.style.display = bfsLegend.style.display === 'none' ? 'block' : 'none';
        });
      }
    // Tooltip für Zeitanzeige sofort anzeigen
    const currentDateTimeBtn = document.getElementById('currentDateTime');
    const currentDateTimeTooltip = document.getElementById('currentDateTimeTooltip');
    if (currentDateTimeBtn && currentDateTimeTooltip) {
      currentDateTimeBtn.addEventListener('mouseenter', () => {
        currentDateTimeTooltip.style.display = 'block';
      });
      currentDateTimeBtn.addEventListener('mouseleave', () => {
        currentDateTimeTooltip.style.display = 'none';
      });
      currentDateTimeBtn.addEventListener('focus', () => {
        currentDateTimeTooltip.style.display = 'block';
      });
      currentDateTimeBtn.addEventListener('blur', () => {
        currentDateTimeTooltip.style.display = 'none';
      });
    }
  // Beim Klick auf die Zeitanzeige aktuellen Zeitpunkt setzen
  document.getElementById('currentDateTime').addEventListener('click', () => {
    const now = new Date();
    // Setze Timeline und Clock direkt auf aktuellen Zeitpunkt
    if (window.viewer) {
      const startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
      const stopDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
      // Nutze die vorhandene Funktion
      if (typeof setTimeline === 'function') {
        setTimeline(startDate, stopDate, now);
      } else {
        // Fallback falls Funktion nicht verfügbar
        const startJD = Cesium.JulianDate.fromDate(startDate);
        const stopJD = Cesium.JulianDate.fromDate(stopDate);
        const currentJD = Cesium.JulianDate.fromDate(now);
        window.viewer.clock.startTime = startJD;
        window.viewer.clock.stopTime = stopJD;
        window.viewer.clock.currentTime = currentJD;
        if (window.viewer.timeline) {
          window.viewer.timeline.updateFromClock();
          window.viewer.timeline.zoomTo(startJD, stopJD);
        }
      }
    }
  });
/**
 * @file app.js
 * Einstiegsskript auf der Root-Ebene von `www/`.
 * Enthält Viewer-Initialisierung und Modulaufrufe (Layers, Coords, Tiles, Infofenster).
 */




(async () => {
  // --- Terrain Provider ---
  const terrainProvider = await window.initTerrainProvider();

  // --- Viewer ---
  const viewer = new Cesium.Viewer("cesiumContainer", {
    terrainProvider,
    imageryProvider: false, // Layer setzen wir separat
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    navigationHelpButton: false,
    fullscreenButton: true,  // Fullscreen-Button aktivieren (wird aber versteckt)
    timeline: true,
    animation: false,
    shadows: false,
    skyBox: false,
    skyAtmosphere: false,
    sceneModePicker: false,
    infoBox: false,            // eigene Info-Box
    selectionIndicator: false, // Ring ausschalten
  });


  // Make viewer globally available for other modules (used for requestRender)
  window.viewer = viewer;

  // Fixpunkte-Layer wird nur über die Checkbox geladen

  // Hide Cesium's default fullscreen button (we use our own)
  if (viewer.fullscreenButton) {
    viewer.fullscreenButton.container.style.display = 'none';
  }

  // Credits/Ion entfernen
  const hide = (fn) => {
    try {
      fn();
    } catch { }
  };
  hide(() => (viewer._creditContainer.style.display = "none"));
  hide(() => (viewer._cesiumWidget._creditContainer.style.display = "none"));
  hide(
    () =>
      (viewer.scene.frameState.creditDisplay._creditTextContainer.style.display =
        "none")
  );
  hide(
    () =>
      (viewer.scene.frameState.creditDisplay._lightboxContainer.style.display =
        "none")
  );
  hide(
    () => (viewer.scene.creditDisplay._creditContainer.style.display = "none")
  );

  // Szene
  viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#d3d3d3");
  viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#d3d3d3");
  viewer.scene.globe.depthTestAgainstTerrain = true;
  viewer.scene.globe.enableLighting = true;
  viewer.shadows = true;
  viewer.scene.shadowMap.enabled = true;
  // --- Lighting Toggle Button ---
  const lightingToggleBtn = document.getElementById("lightingToggleBtn"); // jetzt floating-btn
  let lightingEnabled = true;
  function setLighting(enabled) {
    lightingEnabled = enabled;
    if (enabled) {
      // Normale globale Beleuchtung und Schatten
      viewer.scene.globe.enableLighting = true;
      viewer.shadows = true;
      if (viewer.scene.shadowMap) viewer.scene.shadowMap.enabled = true;
      // Tileset-Schatten aktivieren
      if (window.buildingsTileset) buildingsTileset.shadows = Cesium.ShadowMode.ENABLED;
      if (window.buildingsBFSTileset) buildingsBFSTileset.shadows = Cesium.ShadowMode.ENABLED;
      if (window.roofsTileset) roofsTileset.shadows = Cesium.ShadowMode.ENABLED;
      if (window.pointcloudTileset) pointcloudTileset.shadows = Cesium.ShadowMode.ENABLED;
      // Sonne zurück auf dynamisch
      viewer.scene.light = new Cesium.SunLight();
    } else {
      // Keine globale Beleuchtung, keine Schatten, aber Gebäude mit Standardlicht von Süden
      viewer.scene.globe.enableLighting = false;
      viewer.shadows = false;
      if (viewer.scene.shadowMap) viewer.scene.shadowMap.enabled = false;
      // Tileset-Schatten aus
      if (window.buildingsTileset) buildingsTileset.shadows = Cesium.ShadowMode.DISABLED;
      if (window.buildingsBFSTileset) buildingsBFSTileset.shadows = Cesium.ShadowMode.DISABLED;
      if (window.roofsTileset) roofsTileset.shadows = Cesium.ShadowMode.DISABLED;
      if (window.pointcloudTileset) pointcloudTileset.shadows = Cesium.ShadowMode.DISABLED;
      // Fixierte "Sonne" von Süden (Azimut 180°, Höhe 45°)
      const southLight = new Cesium.DirectionalLight({
        direction: Cesium.Cartesian3.fromElements(0, -1, 1)
      });
      viewer.scene.light = southLight;
    }
    // 🌤️ für Licht/Schatten, 🔆 für beleuchtet ohne Schatten
    lightingToggleBtn.textContent = enabled ? "🌤️" : "🔆";
  }
  lightingToggleBtn.addEventListener("click", () => {
     setLighting(!lightingEnabled);
     // Beschreibung automatisch ausblenden
     const label = document.getElementById('lightingLabel');
     if (label) label.style.display = 'none';
  });
  // Initial: Licht an
  setLighting(false); // Start: Licht aus, Button zeigt "Licht an"

  // FHNW Muttenz
  const fhnwDestination = Cesium.Cartesian3.fromDegrees(
    7.642048508425487,
    47.533,
    450
  );
  const fhnwOrientation = {
    heading: 0,
    pitch: Cesium.Math.toRadians(-35),
    roll: 0,
  };

  // Initiale Kamera
  viewer.camera.setView({
    destination: fhnwDestination,
    orientation: fhnwOrientation,
  });

  // Home-Button ? FHNW
  if (viewer.homeButton && viewer.homeButton.viewModel) {
    viewer.homeButton.viewModel.command.beforeExecute.addEventListener((e) => {
      e.cancel = true;
      viewer.camera.flyTo({
        destination: fhnwDestination,
        orientation: fhnwOrientation,
        duration: 1.5,
      });
    });
  }

  // --- Module initialisieren ---
  initBaseLayerSwitcher(viewer);
  initCoordinateDisplay(viewer);

  // Timeline-Bereich für Gebäude-Visualisierung (1850-2025)
  const endYear = new Date().getFullYear();
  const startYear = endYear - 100; // 100 Jahre zurück
  viewer.clock.startTime = Cesium.JulianDate.fromDate(new Date(startYear, 0, 1));
  viewer.clock.stopTime = Cesium.JulianDate.fromDate(new Date(endYear, 11, 31));
  viewer.clock.currentTime = Cesium.JulianDate.fromDate(new Date(endYear, new Date().getMonth(), new Date().getDate()));
  viewer.clock.clockRange = Cesium.ClockRange.CLAMPED;
  viewer.clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK_MULTIPLIER;
  viewer.clock.multiplier = 60 * 60 * 24 * 365; // 1 Sekunde = 1 Jahr

  if (viewer.timeline) {
    viewer.timeline.updateFromClock();
    viewer.timeline.zoomTo(viewer.clock.startTime, viewer.clock.stopTime);
  }

  // 3D-Gebaeude-Tiles initialisieren
  if (typeof initBuildingBFSTiles === "function") {
    await initBuildingBFSTiles(viewer);
  }
  // Buildings BFS ist jetzt immer aktiv, klassisches Buildings-Tileset entfällt
  if (typeof initRoofTiles === "function") {
    await initRoofTiles(viewer);
  }
  if (typeof initPointcloudTiles === "function") {
    await initPointcloudTiles(viewer);
  }
  if (typeof initMeshGlb === "function") {
    await initMeshGlb(viewer);
  }

  // --- Dropdown oeffnen/schliessen ---
  // Home Button
  const homeBtn = document.getElementById("homeBtn");
  
  homeBtn.addEventListener("click", () => {
    viewer.camera.flyTo({
      destination: fhnwDestination,
      orientation: fhnwOrientation,
      duration: 1.5
    });
    // Set opacity to 0.5 immediately when flying home
    setTimeout(() => {
      homeBtn.style.opacity = '0.5';
    }, 1500); // Match fly duration
  });

  // Check if camera is at home position
  function isAtHomePosition() {
    const position = viewer.camera.position;
    const homePosition = fhnwDestination;
    const distance = Cesium.Cartesian3.distance(position, homePosition);
    
    // Consider "at home" if within 100 meters (ignore orientation)
    return distance < 100;
  }

  // Update home button opacity based on camera position
  viewer.camera.changed.addEventListener(() => {
    if (homeBtn) {
      homeBtn.style.opacity = isAtHomePosition() ? '0.5' : '1';
    }
  });

  // Fullscreen Button - Use Cesium's built-in fullscreen functionality
  const fullscreenBtn = document.getElementById("fullscreenBtn"); // jetzt floating-btn
  let fullscreenActive = false;
  
  if (fullscreenBtn && viewer.fullscreenButton) {
    fullscreenBtn.addEventListener("click", () => {
      viewer.fullscreenButton.viewModel.command();
      fullscreenActive = !fullscreenActive;
      fullscreenBtn.style.opacity = fullscreenActive ? '1' : '0.5';
    });
    
    // Update opacity when fullscreen changes (ESC key)
    document.addEventListener("fullscreenchange", () => {
      fullscreenActive = !!document.fullscreenElement;
      fullscreenBtn.style.opacity = fullscreenActive ? '1' : '0.5';
    });
    document.addEventListener("webkitfullscreenchange", () => {
      fullscreenActive = !!document.webkitFullscreenElement;
      fullscreenBtn.style.opacity = fullscreenActive ? '1' : '0.5';
    });
  }

  // Initialize Timeline Controls
  initTimelineControls(viewer);

  // --- Timeline Controls: Nur Standard Cesium ---
  const timelineControls = document.getElementById('timelineControls');
  function setTimeline(startDate, stopDate, currentDate) {
    // Robust: Nur gültige Date-Objekte verwenden
    function safeDate(d, fallback) {
      if (d instanceof Date && !isNaN(d)) return d;
      if (typeof d === 'string') {
        const dt = new Date(d);
        if (!isNaN(dt)) return dt;
      }
      return fallback instanceof Date ? fallback : new Date();
    }
    const safeStart = safeDate(startDate);
    const safeStop = safeDate(stopDate, safeStart);
    const safeCurrent = safeDate(currentDate, safeStart);
    const startJD = Cesium.JulianDate.fromDate(safeStart);
    const stopJD = Cesium.JulianDate.fromDate(safeStop);
    const currentJD = Cesium.JulianDate.fromDate(safeCurrent);
    viewer.clock.startTime = startJD;
    viewer.clock.stopTime = stopJD;
    viewer.clock.currentTime = currentJD;
    if (viewer.timeline) {
      viewer.timeline.updateFromClock();
      viewer.timeline.zoomTo(startJD, stopJD);
    }
  }
  if (timelineControls) {
    // 100 Jahre Button
    const btnCentury = timelineControls.querySelector('button.timeline-scale-btn[data-scale="century"]');
    if (btnCentury) {
      btnCentury.addEventListener('click', () => {
        const endYear = new Date().getFullYear();
        const startYear = endYear - 100;
        const startDate = new Date(startYear, 0, 1);
        const stopDate = new Date(endYear, 11, 31);
        setTimeline(startDate, stopDate, startDate);
        setLighting(false); // Licht automatisch ausschalten
      });
    }
    // Tag Button
    const btnDay = timelineControls.querySelector('button.timeline-scale-btn[data-scale="day"]');
    if (btnDay) {
      btnDay.addEventListener('click', () => {
        const now = new Date();
        const startDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
        const stopDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
        setTimeline(startDate, stopDate, now);
      });
    }
    // Reset Button
    const btnReset = document.getElementById('resetTimelineBtn');
    if (btnReset) {
      btnReset.addEventListener('click', () => {
        const now = new Date();
        setTimeline(
          new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0),
          new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59),
          now
        );
      });
    }
  }
  
  // Benutzerdefinierte Timeline-Beschriftung: Tag = HH:mm, 100 Jahre = Jahr
  if (viewer.timeline) {
    viewer.timeline.makeLabel = function(time) {
      if (!time) return '';
      const date = Cesium.JulianDate.toGregorianDate(time);
      // Hole aktuelle Zeitspanne
      const startTime = viewer.clock.startTime;
      const endTime = viewer.clock.stopTime;
      let timelineSpan = 0;
      try {
        timelineSpan = Cesium.JulianDate.secondsDifference(endTime, startTime);
      } catch (e) {
        return String(date.year);
      }
      const spanInYears = timelineSpan / (86400 * 365.25);
      if (spanInYears > 50) {
        // 100 Jahre: Nur Jahreszahl
        return String(date.year);
      } else {
        // Tagesansicht: HH:mm
        const pad = n => n.toString().padStart(2, '0');
        return `${pad(date.hour)}:${pad(date.minute)}`;
      }
    };
  }
  
  // Initialize timeline to full year range (1850-2025)
  setTimeout(() => {
    if (viewer.timeline) {
      viewer.timeline.zoomTo(viewer.clock.startTime, viewer.clock.stopTime);
      setTimeout(() => viewer.timeline?.resize(), 50);
    }
  }, 200);

  // Tileset-Dropdown: Nur BFS
  const tilesetBtn = document.getElementById("tilesetBtn");
  const tilesetList = document.getElementById("tilesetList");
  // Entferne klassische Buildings-Checkbox
  const chkBuildings = document.getElementById("chkBuildings");
  if (chkBuildings) chkBuildings.parentElement.remove();
  // BFS-Checkbox wieder sichtbar und beim Start immer aktiv (Gebäude eingeblendet)
  const chkBuildingsBFS = document.getElementById("chkBuildingsBFS");
  if (chkBuildingsBFS) {
    chkBuildingsBFS.checked = true;
    chkBuildingsBFS.parentElement.style.display = '';
    // Gebäude beim Start immer einblenden
    if (window.buildingsBFSTileset) window.buildingsBFSTileset.show = true;
    chkBuildingsBFS.addEventListener('change', () => {
      if (window.buildingsBFSTileset) window.buildingsBFSTileset.show = chkBuildingsBFS.checked;
    });
  }
  tilesetBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = tilesetList.style.display === "block";
    tilesetList.style.display = isOpen ? "none" : "block";
    if (!isOpen) baselayerList.style.display = "none"; // Close other dropdown
  });
  // Farbige Gebäude-Funktion in Floating-Button
  window.bfsColorMode = 'gray'; // 'color' oder 'gray', Standard: grau
  const bfsLegendToggle = document.getElementById('bfsLegendToggle');
  const bfsLegend = document.getElementById('bfsLegend');
  if (bfsLegendToggle && bfsLegend) {
    bfsLegendToggle.addEventListener('click', () => {
      // Beschriftung beim ersten Klick ausblenden
      const label = document.getElementById('bfsLegendLabel');
      if (label && label.style.display !== 'none') label.style.display = 'none';
      const bfs = window.buildingsBFSTileset;
      if (!bfs) return;
      if (window.bfsColorMode === 'color') {
        window.bfsColorMode = 'gray';
        bfsLegendToggle.textContent = '🏢';
        if (bfsLegend) bfsLegend.style.display = 'none';
      } else {
        window.bfsColorMode = 'color';
        bfsLegendToggle.textContent = '🏢';
        if (bfsLegend) bfsLegend.style.display = '';
      }
      if (typeof updateBFSStyle === 'function') updateBFSStyle();
    });
    // Legende beim Start ausblenden (grau ist Standard)
    bfsLegend.style.display = 'none';
  }
  // Timeslider: Style immer synchron zum Farbmodus
  // Beim Start: grau als Standard setzen (Style via updateBFSStyle, damit Highlight weiterhin funktioniert)
  if (window.buildingsBFSTileset) {
    window.bfsColorMode = 'gray';
    if (bfsLegendToggle) bfsLegendToggle.textContent = '🏢';
    if (typeof window.updateBFSStyle === 'function') {
      try { window.updateBFSStyle(); } catch (_) { }
    }
  }

  // Baselayer-Dropdown
  const baselayerBtn = document.getElementById("baselayerBtn");
  const baselayerList = document.getElementById("baselayerList");
  
  baselayerBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = baselayerList.style.display === "block";
    baselayerList.style.display = isOpen ? "none" : "block";
    if (!isOpen) tilesetList.style.display = "none"; // Close other dropdown
  });

  // Click outside to close
  document.addEventListener("click", (e) => {
    if (!tilesetList.contains(e.target) && !tilesetBtn.contains(e.target)) {
      tilesetList.style.display = "none";
    }
    if (!baselayerList.contains(e.target) && !baselayerBtn.contains(e.target)) {
      baselayerList.style.display = "none";
    }
  });

  // Prevent closing when clicking inside the lists
  tilesetList.addEventListener("click", (e) => {
    e.stopPropagation();
  });
  
  baselayerList.addEventListener("click", (e) => {
    e.stopPropagation();
  });

  // Klassifikations-Panel Sichtbarkeit (nur wenn Pointcloud aktiv)
  const chkPointcloud = document.getElementById("chkPointcloud");
  const classificationPanel = document.getElementById("classificationPanel");
  const classificationToggle = document.getElementById("classificationToggle");
  const closeClassificationPanel = document.getElementById("closeClassificationPanel");
  let classificationVisible = false;
  
  if (chkPointcloud && classificationPanel) {
    chkPointcloud.addEventListener("change", () => {
      if (chkPointcloud.checked) {
        classificationPanel.style.display = "block";
        classificationVisible = true;
        if (classificationToggle) {
          classificationToggle.style.display = "none";
        }
      } else {
        classificationPanel.style.display = "none";
        classificationVisible = false;
        if (classificationToggle) {
          classificationToggle.style.display = "none";
        }
      }
    });
  }

  // Classification Panel Toggle Button
  if (classificationToggle) {
    classificationToggle.addEventListener("click", () => {
      classificationVisible = true;
      if (classificationPanel) {
        classificationPanel.style.display = "block";
      }
      classificationToggle.style.display = "none";
    });
  }

  // Close Classification Panel Button
  if (closeClassificationPanel) {
    closeClassificationPanel.addEventListener("click", () => {
      classificationVisible = false;
      if (classificationPanel) {
        classificationPanel.style.display = "none";
      }
      if (classificationToggle && chkPointcloud && chkPointcloud.checked) {
        classificationToggle.style.display = "flex";
      }
    });
  }

  // Infofenster (ausgelagert in tools/infofenster.js)
  if (typeof infofenster === "function") {
    infofenster(viewer);
  }

  // ============================================================================
  // Bounding Box Drawing Tool (Export später)
  // ============================================================================
  const bboxTool = new BoundingBoxTool(viewer);
  const drawBBoxBtn = document.getElementById("drawBBoxBtn");
  const exportPanel = document.getElementById("exportPanel");
  const exportToggle = document.getElementById("exportToggle");
  const closeExportPanel = document.getElementById("closeExportPanel");
  const resetBoxBtn = document.getElementById("resetBoxBtn");
  const redrawBoxBtn = document.getElementById("redrawBoxBtn");
  const exportDataBtn = document.getElementById("exportDataBtn");
  
  let exportPanelVisible = false;

  // Hilfsfunktion: Update Button States basierend auf Box-Existenz
  function updateExportButtonStates() {
    const hasBox = bboxTool.getBounds() !== null;
    
    // Reset Box - nur aktiv wenn Box existiert
    if (resetBoxBtn) {
      if (hasBox) {
        resetBoxBtn.style.color = "#fff";
        resetBoxBtn.disabled = false;
        resetBoxBtn.style.cursor = "pointer";
      } else {
        resetBoxBtn.style.color = "rgba(255, 255, 255, 0.5)";
        resetBoxBtn.disabled = false;
        resetBoxBtn.style.cursor = "not-allowed";
      }
    }
    
    // Export - nur aktiv wenn Box existiert
    if (exportDataBtn) {
      if (hasBox) {
        exportDataBtn.style.color = "#fff";
        exportDataBtn.disabled = false;
        exportDataBtn.style.cursor = "pointer";
      } else {
        exportDataBtn.style.color = "rgba(255, 255, 255, 0.5)";
        exportDataBtn.disabled = false;
        exportDataBtn.style.cursor = "not-allowed";
      }
    }
    
    // Neu zeichnen ist immer verfügbar
    if (redrawBoxBtn) {
      redrawBoxBtn.style.color = "#fff";
      redrawBoxBtn.disabled = false;
      redrawBoxBtn.style.cursor = "pointer";
    }
  }

  // Export Box Button - Toggle zwischen transparent und offen
  if (drawBBoxBtn) {
    drawBBoxBtn.addEventListener("click", () => {
      if (exportPanel) {
        const floatingButtonVisible = exportToggle && exportToggle.style.display === "flex";
        
        if (exportPanelVisible || floatingButtonVisible) {
          // Reset: BBox löschen, Panel schließen, Button transparent, Floating Button verstecken
          bboxTool.clear();
          exportPanel.style.display = "none";
          exportPanelVisible = false;
          drawBBoxBtn.style.opacity = "0.5";
          if (exportToggle) {
            exportToggle.style.display = "none";
          }
          updateExportButtonStates();
        } else {
          // Panel öffnen, Button aktiv
          exportPanel.style.display = "block";
          exportPanelVisible = true;
          drawBBoxBtn.style.opacity = "1";
          if (exportToggle) {
            exportToggle.style.display = "none";
          }
          updateExportButtonStates();
        }
      }
    });
  }

  // Floating Button Toggle
  if (exportToggle) {
    exportToggle.addEventListener("click", () => {
      if (exportPanel) {
        exportPanel.style.display = "block";
        exportPanelVisible = true;
        drawBBoxBtn.style.opacity = "1";
        exportToggle.style.display = "none";
        updateExportButtonStates();
      }
    });
  }

  // Close Button - zeigt Floating Button
  if (closeExportPanel) {
    closeExportPanel.addEventListener("click", () => {
      if (exportPanel) {
        exportPanel.style.display = "none";
        exportPanelVisible = false;
        drawBBoxBtn.style.opacity = "1"; // Hauptbutton bleibt aktiv
        if (exportToggle) {
          exportToggle.style.display = "flex";
        }
        updateExportButtonStates();
      }
    });
  }

  // Reset Box
  if (resetBoxBtn) {
    resetBoxBtn.addEventListener("click", () => {
      bboxTool.clear();
      updateExportButtonStates();
    });
  }

  // Neu zeichnen
  if (redrawBoxBtn) {
    redrawBoxBtn.addEventListener("click", () => {
      bboxTool.clear();
      updateExportButtonStates();
      bboxTool.activate((bounds) => {
        // Box erstellt - öffne Panel wieder
        if (exportPanel) {
          exportPanel.style.display = "block";
          exportPanelVisible = true;
          updateExportButtonStates();
        }
        if (exportToggle) {
          exportToggle.style.display = "none";
        }
      });
      
      // Schließe Panel während Zeichnen
      if (exportPanel) {
        exportPanel.style.display = "none";
        exportPanelVisible = false;
      }
    });
  }

  // Export Button - Exportiert Terrain als GLB
  if (exportDataBtn) {
    exportDataBtn.addEventListener("click", async () => {
      const bounds = bboxTool.getBounds();
      if (!bounds) {
        alert("Bitte zuerst eine Box zeichnen!");
        return;
      }

      if (!bounds.footprint || !Array.isArray(bounds.footprint) || bounds.footprint.length < 4) {
        alert("Box-Footprint fehlt. Bitte Box neu zeichnen.");
        return;
      }

      // Trigger file download (same-origin via nginx proxy -> export_api)
      const ts = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      const filename = `buildings_${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}_${pad(ts.getHours())}${pad(ts.getMinutes())}${pad(ts.getSeconds())}.obj`;

      const polyParam = encodeURIComponent(JSON.stringify(bounds.footprint));
      const url = `/export/buildings.obj?poly=${polyParam}&filename=${encodeURIComponent(filename)}`;

      // Basic UX: disable button briefly to avoid double-click
      const prevText = exportDataBtn.textContent;
      exportDataBtn.textContent = "Export läuft...";
      exportDataBtn.disabled = true;

      try {
        window.location.href = url;
      } finally {
        // Re-enable after a short delay (download handled by browser)
        setTimeout(() => {
          exportDataBtn.textContent = prevText;
          exportDataBtn.disabled = false;
          updateExportButtonStates();
        }, 1500);
      }
      
      console.log("Export OBJ gestartet", { bounds, url });
    });
  }

  // Height Slider für Box-Höhe
  const boxHeightSlider = document.getElementById("boxHeightSlider");
  const topHeightValue = document.getElementById("topHeightValue");
  if (boxHeightSlider && topHeightValue) {
    boxHeightSlider.addEventListener("input", (e) => {
      const height = parseInt(e.target.value);
      topHeightValue.textContent = height;
      bboxTool.setBoxHeight(height);
    });
  }

  // Initial state: Reset automatisch triggern beim Start
  setTimeout(() => {
    if (resetBoxBtn) {
      resetBoxBtn.click();
    }
  }, 100);
  // --- Pop-up für Licht/Schatten-Button beim Start ---
  function showLightingHint() {
    const btn = document.getElementById('lightingToggleBtn');
    const hint = document.createElement('div');
    hint.id = 'lightingHintPopup';
    hint.innerHTML = '<b>Licht & Schatten</b><br>Mit diesem Button kannst du zwischen realistischem Licht mit Schatten (🌤️) und einfacher Beleuchtung (🔆) umschalten.';
    hint.style.position = 'fixed';
    hint.style.zIndex = 2000;
    hint.style.background = 'rgba(0,0,0,0.92)';
    hint.style.color = '#fff';
    hint.style.padding = '14px 20px';
    hint.style.borderRadius = '12px';
    hint.style.boxShadow = '0 6px 24px rgba(0,0,0,0.5)';
    hint.style.fontSize = '15px';
    hint.style.maxWidth = '240px';
    hint.style.pointerEvents = 'auto';
    hint.style.border = '2px solid #ffd700';
    let posSet = false;
    if (btn) {
      try {
        const rect = btn.getBoundingClientRect();
        hint.style.left = (rect.left + rect.width + 12) + 'px';
        hint.style.top = (rect.top + rect.height/2 - 24) + 'px';
        posSet = true;
      } catch {}
    }
    if (!posSet) {
      // Fallback: rechts unten mittig
      hint.style.right = '30px';
      hint.style.bottom = '120px';
    }
    document.body.appendChild(hint);
    // Pop-up bleibt einfach stehen, keine Klick-Entfernung
  }
  window.addEventListener('DOMContentLoaded', () => {
    window.onload = () => {
      setTimeout(showLightingHint, 1200);
    };
  });
})();
