/**
 * Initialisiert den Terrain Provider und gibt ihn zurück.
 * @returns {Promise<Cesium.CesiumTerrainProvider>} Terrain Provider
 */
function getTilesBaseUrl() {
  // Alte Logik: Tiles kommen von http://<LOCAL_IP>/...
  return `http://${window.LOCAL_IP}`;
}

async function initTerrainProvider() {
  const baseUrl = getTilesBaseUrl();
  return await Cesium.CesiumTerrainProvider.fromUrl(
    `${baseUrl}/terrain_qm`,
    {
      requestVertexNormals: true,
      requestWaterMask: false,
    }
  );
}
// Terrain Provider global verfügbar machen
window.initTerrainProvider = initTerrainProvider;
/**
 * @file tools/tiles.js
 * Initialisiert 3D-Tiles für Buildings, Roofs und Pointclouds und
 * stellt einfache UI-Verknüpfungen (Checkboxen) zur Sichtbarkeit bereit.
 */

/**
 * Initialisiert das 3D-Buildings-Tileset (mit BFS-Daten) und registriert es global.
 * Gebäude werden basierend auf Baujahr und Timeline-Zeit ein-/ausgeblendet.
 * @param {Cesium.Viewer} viewer Cesium Viewer
 * @returns {Promise<Cesium.Cesium3DTileset|undefined>} geladener Tileset oder undefined bei Fehler
 */
// Initialisiert das klassische Buildings-Tileset (ohne BFS)
async function initBuildingTiles(viewer) {
  const baseUrl = getTilesBaseUrl();
  const tilesetUrl = `${baseUrl}/buildings/tileset.json`;
  let tileset;
  try {
    tileset = await Cesium.Cesium3DTileset.fromUrl(tilesetUrl);
    viewer.scene.primitives.add(tileset);
    console.log("Building-Tileset erfolgreich geladen:", tileset);
  } catch (err) {
    console.error("Fehler beim Laden der 3D-Building-Tiles:", err);
    return;
  }
  tileset.shadows = Cesium.ShadowMode.ENABLED;
  tileset.maximumScreenSpaceError = 4.0;
  tileset.dynamicScreenSpaceError = true;
  tileset.style = new Cesium.Cesium3DTileStyle({ color: "color('lightgray')" });
  window.buildingsTileset = tileset;
  const chk = document.getElementById("chkBuildings");
  tileset.show = chk ? chk.checked : true;
  if (chk) {
    chk.addEventListener("change", () => { tileset.show = chk.checked; });
  }
  return tileset;
}

// Initialisiert das BFS-Buildings-Tileset (ohne Timeline-Filterung)
async function initBuildingBFSTiles(viewer) {
  const baseUrl = getTilesBaseUrl();
  const tilesetUrl = `${baseUrl}/buildings_bfs/tileset.json`;
  let tileset;
  try {
    tileset = await Cesium.Cesium3DTileset.fromUrl(tilesetUrl);
    viewer.scene.primitives.add(tileset);
    console.log("Building BFS-Tileset erfolgreich geladen:", tileset);
  } catch (err) {
    console.error("Fehler beim Laden der 3D-Building-BFS-Tiles:", err);
    return;
  }
  tileset.shadows = Cesium.ShadowMode.ENABLED;
  tileset.maximumScreenSpaceError = 4.0;
  tileset.dynamicScreenSpaceError = true;
  function updateBFSStyle() {
    const currentTime = viewer.clock.currentTime;
    const currentYear = Cesium.JulianDate.toGregorianDate(currentTime).year;
    const showExpr = "Boolean(${baujahr}) && !isNaN(Number(${baujahr})) ? Number(${baujahr}) <= " + currentYear + " : true";

    // Optionales Highlight für selektiertes Gebäude (aus infofenster.js)
    let highlightCondition = null;
    if (window.selectedBuildingEgid !== undefined && window.selectedBuildingEgid !== null && window.selectedBuildingEgid !== "") {
      const selectedEgidNumber = Number(window.selectedBuildingEgid);
      if (Number.isFinite(selectedEgidNumber)) {
        highlightCondition = [
          "Boolean(${egid}) && Number(${egid}) === " + selectedEgidNumber,
          "color('yellow', 0.35)"
        ];
      }
    }

    if (window.bfsColorMode === 'gray') {
      tileset.style = new Cesium.Cesium3DTileStyle({
        show: showExpr,
        color: highlightCondition
          ? { conditions: [highlightCondition, ["true", "color('lightgray', 1.0)"]] }
          : "color('lightgray', 1.0)"
      });
      return;
    }

    const conditions = [
      ["!Boolean(${baujahr}) || isNaN(Number(${baujahr}))", "color('lightgray', 0.8)"],
      ["Number(${baujahr}) < 1900", "color('red', 1.0)"],
      ["Number(${baujahr}) < 1950", "color('#ff6600', 1.0)"],
      ["Number(${baujahr}) < 1980", "color('yellow', 1.0)"],
      ["Number(${baujahr}) < 2000", "color('lime', 1.0)"],
      ["Number(${baujahr}) < 2010", "color('green', 1.0)"],
      ["true", "color('#00b300', 1.0)"],
    ];
    if (highlightCondition) conditions.unshift(highlightCondition);

    tileset.style = new Cesium.Cesium3DTileStyle({
      show: showExpr,
      color: { conditions }
    });
  }
  updateBFSStyle();
  window.updateBFSStyle = updateBFSStyle;
  // Timeline-Update: nur bei Jahr-Änderung neu setzen
  let lastYear = Cesium.JulianDate.toGregorianDate(viewer.clock.currentTime).year;
  viewer.clock.onTick.addEventListener(() => {
    const year = Cesium.JulianDate.toGregorianDate(viewer.clock.currentTime).year;
    if (year !== lastYear && tileset.show) {
      updateBFSStyle();
      lastYear = year;
    }
  });
  window.buildingsBFSTileset = tileset;
  const chk = document.getElementById("chkBuildingsBFS");
  tileset.show = chk ? chk.checked : false;
  if (chk) {
    chk.addEventListener("change", () => { tileset.show = chk.checked; });
  }
  return tileset;
}


/**
 * Initialisiert das 3D-Roofs-Tileset. Hebt Dächer leicht an, um Z-Fighting
 * mit Terrain zu reduzieren, und setzt einen dunkleren Standardstil.
 * @param {Cesium.Viewer} viewer Cesium Viewer
 * @returns {Promise<Cesium.Cesium3DTileset|undefined>} geladener Tileset oder undefined bei Fehler
 */
async function initRoofTiles(viewer) {
  console.log("initRoofTiles() wird ausgefuehrt...");

  const baseUrl = getTilesBaseUrl();
  const tilesetUrl = `${baseUrl}/roofs/tileset.json`;

  let tileset;
  try {
    tileset = await Cesium.Cesium3DTileset.fromUrl(tilesetUrl);
    viewer.scene.primitives.add(tileset);
    console.log("Roof-Tileset erfolgreich geladen:", tileset);
  } catch (err) {
    console.error("Fehler beim Laden der 3D-Roof-Tiles:", err);
    return;
  }

  // Leichter Z-Offset, um Überlappungen mit Terrain zu vermeiden (0.01 m)
  const offset = Cesium.Cartesian3.fromElements(0, 0, 0.01);
  tileset.modelMatrix = Cesium.Matrix4.fromTranslation(offset);

  // Dächer werfen/empfangen ebenfalls Schatten
  tileset.shadows = Cesium.ShadowMode.ENABLED;

  // Performance-Tuning
  tileset.maximumScreenSpaceError = 4.0;
  tileset.dynamicScreenSpaceError = true;

  // Standardstil für Dächer (etwas dunkler damit Altersfarben hervorstechen)
  tileset.style = new Cesium.Cesium3DTileStyle({ color: "color('#995f5fff')" });

  window.roofsTileset = tileset;
  window._defaultRoofStyle = tileset.style;

  const chk = document.getElementById("chkRoofs");
  tileset.show = chk ? chk.checked : true;
  if (chk) {
    chk.addEventListener("change", () => { tileset.show = chk.checked; });
  }

  return tileset;
}


/**
 * Initialisiert das Punktwolken-Tileset mit Klassen-basiertem Styling.
 * UI-Elemente (Master-Checkbox und Klassen-Checkboxen) steuern, welche
 * Klassifikationen gerendert werden.
 * @param {Cesium.Viewer} viewer Cesium Viewer
 * @returns {Promise<Cesium.Cesium3DTileset|undefined>} geladener Tileset oder undefined bei Fehler
 */
async function initPointcloudTiles(viewer) {
  console.log("initPointcloudTiles() wird ausgefuehrt...");

  let currentResolution = "low";
  let tileset;
  
  const baseUrl = getTilesBaseUrl();
  const tilesetUrls = {
    low: `${baseUrl}/pointcloud/swisstopo_low/tileset.json`,
    high: `${baseUrl}/pointcloud/swisstopo_high/tileset.json`
  };

  // UI: Master-Switch + Klassen-Checkboxen
  const masterCheckbox = document.getElementById("chkPointcloud");
  const classCheckboxes = Array.from(document.querySelectorAll(".pcClass"));

  // Funktion zum Laden/Wechseln der Resolution
  async function loadResolution(resolution) {
    const url = tilesetUrls[resolution];
    
    // Entferne altes Tileset falls vorhanden
    if (tileset) {
      viewer.scene.primitives.remove(tileset);
    }
    
    try {
      tileset = await Cesium.Cesium3DTileset.fromUrl(url);
      viewer.scene.primitives.add(tileset);
      console.log(`Pointcloud-Tileset (${resolution}) erfolgreich geladen:`, tileset);

      window.pointcloudTileset = tileset;
      
      // Schatten deaktivieren
      tileset.shadows = Cesium.ShadowMode.DISABLED;
      
      // Style neu anwenden
      updatePointcloudStyleFromUI();
      
      currentResolution = resolution;
    } catch (err) {
      console.error(`Fehler beim Laden der Punktwolken-Tiles (${resolution}):`, err);
    }
  }
  
  // Initial Low-Res laden
  await loadResolution("low");

  // Klassifikations-Styles (RFC: Farben nach Klasse)
  const classStyles = {
    2: { color: "#5a3a19" },  // Boden
    3: { color: "#0f4d0f" },  // Vegetation niedrig
    4: { color: "#176b17" },  // Vegetation mittel
    5: { color: "#228b22" },  // Vegetation hoch
    6: { color: "#ff9900" },  // Gebäude
    7: { color: "#703070" },  // Rauschen
    9: { color: "#006c9e" }   // Wasser
  };

  // Basis-Punktgröße
  const BASE_POINT_SIZE = 2.4;

  // Erzeugt color-conditions für das Cesium-Style-Objekt aus einer Menge selektierter Klassen
  function buildColorConditions(selectedSet) {
    const conditions = [];
    for (const [clsStr, style] of Object.entries(classStyles)) {
      const cls = Number(clsStr);
      if (selectedSet.has(cls)) {
        conditions.push([
          "${CLASSIFICATION} === " + cls,
          `color('${style.color}', 1.0)`
        ]);
      }
    }
    // Fallback: alles andere transparent
    conditions.push(["true", "color('white', 0.0)"]);
    return conditions;
  }

  // Erzeugt show-conditions: wenn keine Klasse selektiert, nichts rendern
  function buildShowConditions(selectedValues) {
    if (selectedValues.length === 0) {
      return [["true", "false"]]; // nichts rendern
    }
    const expr = selectedValues.map(cls => "${CLASSIFICATION} === " + cls).join(" || ");
    return [[expr, "true"], ["true", "false"]];
  }

  // Liest UI-Status und setzt tileset.style + tileset.show entsprechend
  function updatePointcloudStyleFromUI() {
    const masterOn = masterCheckbox ? masterCheckbox.checked : false;
    const selectedValues = classCheckboxes.filter(cb => cb.checked).map(cb => Number(cb.value));
    const hasSelectedClasses = selectedValues.length > 0;

    if (!masterOn || !hasSelectedClasses) {
      tileset.show = false;
      viewer.scene.requestRender();
      return;
    }

    tileset.show = true;
    const selectedSet = new Set(selectedValues);

    tileset.style = new Cesium.Cesium3DTileStyle({
      pointSize: BASE_POINT_SIZE,
      color: { conditions: buildColorConditions(selectedSet) },
      show:  { conditions: buildShowConditions(selectedValues) }
    });

    viewer.scene.requestRender();
  }

  // Initialer Zustand basierend auf vorhandenen Checkboxen
  updatePointcloudStyleFromUI();

  // Event-Handler: UI-Änderungen neu anwenden
  if (masterCheckbox) masterCheckbox.addEventListener("change", updatePointcloudStyleFromUI);
  classCheckboxes.forEach(cb => cb.addEventListener("change", updatePointcloudStyleFromUI));
  
  // Resolution-Toggle Button
  const resToggleBtn = document.getElementById("resolutionToggle");
  if (resToggleBtn) {
    resToggleBtn.addEventListener("click", () => {
      const newRes = currentResolution === "low" ? "high" : "low";
      loadResolution(newRes);
      resToggleBtn.textContent = newRes === "low" ? "High-Res" : "Low-Res";
    });
  }

  // Optional: FPS zum Debuggen
  // viewer.scene.debugShowFramesPerSecond = true;

  return tileset;
}

/**
 * Loads a single GLB mesh from /mesh and positions it using metadata.xml.
 * Expected metadata format:
 *   <SRS>ENU:lat,lon</SRS>
 *   <SRSOrigin>e,n,u</SRSOrigin>
 *
 * The GLB is assumed to be authored in local ENU meters.
 * @param {Cesium.Viewer} viewer Cesium Viewer
 */
async function initMeshGlb(viewer) {
  const chk = document.getElementById("chkMeshGLB");
  if (!chk) return;

  const metadataUrl = "/mesh/metadata.xml";
  const defaultGlbUrl = "/mesh/20251222_CMU.glb";
  const glbUrl = window.MESH_GLB_URL || defaultGlbUrl;

  let model;
  let modelLoaded = false;
  let metadataCache = null;
  let prevGlobeShow;

  async function readMetadata() {
    const res = await fetch(metadataUrl, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} while fetching ${metadataUrl}`);
    }
    const xmlText = await res.text();
    const doc = new DOMParser().parseFromString(xmlText, "application/xml");

    const srsText = doc.querySelector("SRS")?.textContent?.trim() || "";
    const srsOriginText = doc.querySelector("SRSOrigin")?.textContent?.trim() || "0,0,0";
    const heightOffsetText = doc.querySelector("HeightOffsetM")?.textContent?.trim();

    // SRS: ENU:lat,lon (lat first)
    const match = /^ENU\s*:\s*([-+\d.]+)\s*,\s*([-+\d.]+)\s*$/i.exec(srsText);
    if (!match) {
      throw new Error(`Unsupported SRS in metadata.xml: "${srsText}" (expected "ENU:lat,lon")`);
    }
    const lat = Number(match[1]);
    const lon = Number(match[2]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      throw new Error(`Invalid ENU origin lat/lon: ${match[1]}, ${match[2]}`);
    }

    // Origin offset in ENU meters
    const parts = srsOriginText.split(",").map((p) => Number(String(p).trim()));
    const e = Number.isFinite(parts[0]) ? parts[0] : 0;
    const n = Number.isFinite(parts[1]) ? parts[1] : 0;
    const u = Number.isFinite(parts[2]) ? parts[2] : 0;

    const heightOffsetM = heightOffsetText ? Number(heightOffsetText) : 0;

    return { lat, lon, e, n, u, heightOffsetM };
  }

  async function getMetadata() {
    if (metadataCache) return metadataCache;
    metadataCache = await readMetadata();
    return metadataCache;
  }

  async function computeTerrainHeight(lon, lat) {
    // Try multiple strategies; if everything fails, fall back to camera height.
    let height;
    const carto = Cesium.Cartographic.fromDegrees(lon, lat, 0);
    try {
      const updated = await Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, [carto]);
      if (updated && updated[0] && Number.isFinite(updated[0].height)) {
        height = updated[0].height;
      }
    } catch {
      // ignore
    }

    if (!Number.isFinite(height)) {
      const start = performance.now();
      while (!Number.isFinite(height) && performance.now() - start < 2500) {
        try {
          viewer.scene.requestRender();
          const h = viewer.scene.globe.getHeight(carto);
          if (Number.isFinite(h)) height = h;
        } catch {
          // ignore
        }
        if (!Number.isFinite(height)) {
          await new Promise((r) => setTimeout(r, 100));
        }
      }
    }

    if (!Number.isFinite(height)) {
      const camH = viewer.camera?.positionCartographic?.height;
      height = Number.isFinite(camH) ? camH : 0;
      console.warn("Mesh GLB: terrain height unavailable, using camera height fallback:", height);
    }
    return height;
  }

  function applyWorldUpOffset(modelMatrix, upMeters) {
    if (!Number.isFinite(upMeters) || upMeters === 0) return modelMatrix;

    // Extract Up axis (3rd column) from ENU->Fixed-like matrix; normalize and translate.
    const up = new Cesium.Cartesian3(modelMatrix[8], modelMatrix[9], modelMatrix[10]);
    const mag = Cesium.Cartesian3.magnitude(up);
    if (!Number.isFinite(mag) || mag === 0) return modelMatrix;
    Cesium.Cartesian3.divideByScalar(up, mag, up);
    const delta = Cesium.Cartesian3.multiplyByScalar(up, upMeters, new Cesium.Cartesian3());
    const t = Cesium.Matrix4.fromTranslation(delta);
    return Cesium.Matrix4.multiply(t, modelMatrix, new Cesium.Matrix4());
  }

  // --- Optional: align this ENU-authored GLB to a LV95 reference GLB (hidden) ---
  // This restores the previously working behavior (correct position/rotation/height)
  // while keeping only ONE visible GLB layer for deploy.
  async function tryAlignUsingLv95Reference() {
    const lv95Url = window.MESH_GLB_LV95_URL || "/mesh/20251222_CMU_LV95.glb";

    function lv95ToWgs84(easting, northing) {
      const y = (easting - 2600000.0) / 1000000.0;
      const x = (northing - 1200000.0) / 1000000.0;

      let lat =
        16.9023892 +
        3.238272 * x -
        0.270978 * y * y -
        0.002528 * x * x -
        0.0447 * y * y * x -
        0.0140 * x * x * x;
      let lon =
        2.6779094 +
        4.728982 * y +
        0.791484 * y * x +
        0.1306 * y * x * x -
        0.0436 * y * y * y;

      lat = (lat * 100.0) / 36.0;
      lon = (lon * 100.0) / 36.0;
      return { lat, lon };
    }

    function chooseLv95AxisMapping(cx, cy) {
      const candidates = [
        { eAxis: 'x', eSign: +1, nAxis: 'y', nSign: +1, label: 'E=+x, N=+y' },
        { eAxis: 'x', eSign: +1, nAxis: 'y', nSign: -1, label: 'E=+x, N=-y' },
        { eAxis: 'x', eSign: -1, nAxis: 'y', nSign: +1, label: 'E=-x, N=+y' },
        { eAxis: 'x', eSign: -1, nAxis: 'y', nSign: -1, label: 'E=-x, N=-y' },
        { eAxis: 'y', eSign: +1, nAxis: 'x', nSign: +1, label: 'E=+y, N=+x' },
        { eAxis: 'y', eSign: +1, nAxis: 'x', nSign: -1, label: 'E=+y, N=-x' },
        { eAxis: 'y', eSign: -1, nAxis: 'x', nSign: +1, label: 'E=-y, N=+x' },
        { eAxis: 'y', eSign: -1, nAxis: 'x', nSign: -1, label: 'E=-y, N=-x' },
      ];

      function axisValue(axis) {
        return axis === 'x' ? cx : cy;
      }

      function rangeScore(v, min, max) {
        if (!Number.isFinite(v)) return 1e12;
        if (v < min) return (min - v);
        if (v > max) return (v - max);
        return 0;
      }

      let best = null;
      let bestScore = Number.POSITIVE_INFINITY;
      for (const c of candidates) {
        const e = c.eSign * axisValue(c.eAxis);
        const n = c.nSign * axisValue(c.nAxis);
        const s = rangeScore(e, 2300000, 2900000) + rangeScore(n, 900000, 1500000);
        if (s < bestScore) {
          bestScore = s;
          best = { ...c, e0: e, n0: n, score: s };
        }
      }
      return best;
    }

    function buildModelToEnuRotation(mapping) {
      const e = mapping.eAxis;
      const n = mapping.nAxis;

      const Ex = e === 'x' ? mapping.eSign : 0;
      const Ey = e === 'y' ? mapping.eSign : 0;
      const Ez = 0;

      const Nx = n === 'x' ? mapping.nSign : 0;
      const Ny = n === 'y' ? mapping.nSign : 0;
      const Nz = 0;

      const Ux = 0;
      const Uy = 0;
      const Uz = 1;

      return new Cesium.Matrix3(
        Ex, Nx, Ux,
        Ey, Ny, Uy,
        Ez, Nz, Uz
      );
    }

    async function oncePostRender() {
      return new Promise((resolve) => {
        const cb = () => {
          viewer.scene.postRender.removeEventListener(cb);
          resolve();
        };
        viewer.scene.postRender.addEventListener(cb);
        viewer.scene.requestRender();
      });
    }

    async function waitModelReady(m) {
      if (!m) return;
      if (m.readyPromise && typeof m.readyPromise.then === 'function') {
        await m.readyPromise;
      } else if (m.readyEvent && typeof m.readyEvent.addEventListener === 'function' && !m.ready) {
        await new Promise((resolve) => m.readyEvent.addEventListener(resolve));
      } else {
        const start = performance.now();
        while (!m.ready && performance.now() - start < 5000) {
          await new Promise((r) => setTimeout(r, 50));
        }
      }
      await oncePostRender();
    }

    let lv95Model;
    try {
      lv95Model = await Cesium.Model.fromGltfAsync({ url: lv95Url });
    } catch {
      return false; // LV95 reference not available
    }
    if (!lv95Model) return false;

    // Add hidden so Cesium computes bounds; never show it.
    lv95Model.show = false;
    viewer.scene.primitives.add(lv95Model);
    await waitModelReady(lv95Model);

    const c0 = lv95Model.boundingSphere?.center;
    const cx = c0?.x;
    const cy = c0?.y;
    const cz = c0?.z;
    const isLikelyAbsoluteLv95 =
      Number.isFinite(cx) && Number.isFinite(cy) && (Math.abs(cx) > 100000 || Math.abs(cy) > 100000);
    if (!isLikelyAbsoluteLv95) {
      try {
        viewer.scene.primitives.remove(lv95Model);
        if (typeof lv95Model.destroy === 'function') lv95Model.destroy();
      } catch { }
      return false;
    }

    const mapping = chooseLv95AxisMapping(cx, cy);
    if (!mapping || mapping.score > 500000) {
      try {
        viewer.scene.primitives.remove(lv95Model);
        if (typeof lv95Model.destroy === 'function') lv95Model.destroy();
      } catch { }
      return false;
    }

    const { lat, lon } = lv95ToWgs84(mapping.e0, mapping.n0);
    const height = await computeTerrainHeight(lon, lat);
    const originCartesian = Cesium.Cartesian3.fromDegrees(lon, lat, height);
    const enuToFixed = Cesium.Transforms.eastNorthUpToFixedFrame(originCartesian);

    const recenterModel = Cesium.Matrix4.fromTranslation(
      new Cesium.Cartesian3(
        Number.isFinite(cx) ? -cx : 0,
        Number.isFinite(cy) ? -cy : 0,
        Number.isFinite(cz) ? -cz : 0
      )
    );

    let rotModelToEnu = buildModelToEnuRotation(mapping);
    const rot180 = Cesium.Matrix3.fromRotationZ(Cesium.Math.PI);
    rotModelToEnu = Cesium.Matrix3.multiply(rot180, rotModelToEnu, new Cesium.Matrix3());
    const modelToEnu = Cesium.Matrix4.fromRotationTranslation(rotModelToEnu, Cesium.Cartesian3.ZERO);
    const localLv95 = Cesium.Matrix4.multiply(modelToEnu, recenterModel, new Cesium.Matrix4());
    const modelMatrixLv95 = Cesium.Matrix4.multiply(enuToFixed, localLv95, new Cesium.Matrix4());

    // Apply LV95 placement to hidden ref so we get the correct world-space center.
    lv95Model.modelMatrix = modelMatrixLv95;
    viewer.scene.requestRender();
    await oncePostRender();
    const targetCenter = lv95Model.boundingSphere?.center;

    // Now place the LOCAL ENU GLB at the same origin + rotation, then center-align.
    const { e, n, u } = await getMetadata();
    const offset = Cesium.Matrix4.fromTranslation(new Cesium.Cartesian3(e, n, u));
    const localBase = Cesium.Matrix4.multiply(
      offset,
      Cesium.Matrix4.fromRotationTranslation(rotModelToEnu, Cesium.Cartesian3.ZERO),
      new Cesium.Matrix4()
    );
    const baseWorld = Cesium.Matrix4.multiply(enuToFixed, localBase, new Cesium.Matrix4());
    model.modelMatrix = baseWorld;
    viewer.scene.requestRender();
    await oncePostRender();

    const myCenter = model.boundingSphere?.center;
    if (targetCenter && myCenter) {
      const delta = Cesium.Cartesian3.subtract(targetCenter, myCenter, new Cesium.Cartesian3());
      const worldTranslate = Cesium.Matrix4.fromTranslation(delta);
      model.modelMatrix = Cesium.Matrix4.multiply(worldTranslate, model.modelMatrix, new Cesium.Matrix4());
      viewer.scene.requestRender();
    }

    // Optional extra height offset from metadata.xml (meters, positive = up)
    try {
      const { heightOffsetM } = await getMetadata();
      if (Number.isFinite(heightOffsetM) && heightOffsetM !== 0) {
        model.modelMatrix = applyWorldUpOffset(model.modelMatrix, heightOffsetM);
        viewer.scene.requestRender();
      }
    } catch {
      // ignore
    }

    // Cleanup LV95 reference model.
    try {
      viewer.scene.primitives.remove(lv95Model);
      if (typeof lv95Model.destroy === 'function') lv95Model.destroy();
    } catch { }

    return true;
  }

  async function computeModelMatrixFromMetadata() {
    const { lat, lon, e, n, u, heightOffsetM } = await getMetadata();
    const height = await computeTerrainHeight(lon, lat);

    if (window.DEBUG_MESH_GLB) {
      console.log("Mesh GLB origin (lat,lon,height):", {
        lat,
        lon,
        height,
        enuOffset: { e, n, u },
      });
    }

    const originCartesian = Cesium.Cartesian3.fromDegrees(lon, lat, height);
    const enuToFixed = Cesium.Transforms.eastNorthUpToFixedFrame(originCartesian);
    const offset = Cesium.Matrix4.fromTranslation(new Cesium.Cartesian3(e, n, u + (Number.isFinite(heightOffsetM) ? heightOffsetM : 0)));
    return Cesium.Matrix4.multiply(enuToFixed, offset, new Cesium.Matrix4());
  }

  async function ensureLoaded() {
    if (modelLoaded) return model;

    const modelMatrix = await computeModelMatrixFromMetadata();
    model = await Cesium.Model.fromGltfAsync({
      url: glbUrl,
      modelMatrix,
    });
    // Make sure it's visible even if it's small.
    model.minimumPixelSize = 32;
    model.shadows = Cesium.ShadowMode.ENABLED;
    // Slightly brighten the mesh (keeps texture details, avoids heavy rendering hacks).
    try {
      model.color = Cesium.Color.WHITE;
      model.colorBlendMode = Cesium.ColorBlendMode.MIX;
      model.colorBlendAmount = 0.15;
    } catch {
      // ignore (older Cesium builds)
    }
    model.show = true;
    viewer.scene.primitives.add(model);
    modelLoaded = true;
    window.meshGlbModel = model;
    viewer.scene.requestRender();

    // After the basic ENU placement, optionally override placement using LV95 reference (hidden).
    // This restores the previously correct location without exposing LV95 as a layer.
    try {
      await tryAlignUsingLv95Reference();
    } catch {
      // ignore
    }
    return model;
  }

  async function setEnabled(enabled) {
    if (!enabled) {
      if (modelLoaded && model) {
        model.show = false;
        // Restore terrain/globe visibility
        if (typeof prevGlobeShow === 'boolean') {
          viewer.scene.globe.show = prevGlobeShow;
        } else {
          viewer.scene.globe.show = true;
        }
        viewer.scene.requestRender();
      }
      return;
    }

    try {
      await ensureLoaded();
      if (model) model.show = true;
      // Hide terrain/globe while the GLB is shown
      if (typeof prevGlobeShow !== 'boolean') {
        prevGlobeShow = viewer.scene.globe.show;
      }
      viewer.scene.globe.show = false;
      viewer.scene.requestRender();
    } catch (err) {
      console.error("Failed to load/position GLB mesh:", err);
      // Reset checkbox on failure to avoid confusing UI state
      chk.checked = false;
    }
  }

  chk.addEventListener("change", () => {
    setEnabled(!!chk.checked);
  });

  // Initial state
  await setEnabled(!!chk.checked);
}

// Export
window.initMeshGlb = initMeshGlb;

