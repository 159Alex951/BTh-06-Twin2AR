// Fixpunkte-Layer: GeoJSON laden und steuern
let fixpunkteEntities = [];
let fixpunkteLoaded = false;
async function loadFixpunkteLayer(viewer) {
  if (fixpunkteLoaded) {
    fixpunkteEntities.forEach(e => e.show = true);
    return;
  }
  try {
    const response = await fetch("/point/2021_Fixpunkte_FHNW_wgs84.geojson");
    if (!response.ok) throw new Error("HTTP " + response.status);
    const geojson = await response.json();
    if (!geojson.features || !Array.isArray(geojson.features)) throw new Error("GeoJSON hat keine Features");
    fixpunkteEntities = geojson.features.map(f => {
      const coords = f.geometry.coordinates;
      const name = f.properties.Nr || "Fixpunkt";
      const position = Cesium.Cartesian3.fromDegrees(coords[0], coords[1], coords[2] || 0);
      // Glatte, runde Kugel (ohne Outline, leicht rot)
      return viewer.entities.add({
        position,
        ellipsoid: {
          radii: new Cesium.Cartesian3(0.5, 0.5, 0.5),
          material: Cesium.Color.fromCssColorString('#ffaaaa'),
          outline: false,
          heightReference: Cesium.HeightReference.NONE
        },
        label: {
          text: name,
          font: 'bold 11px Bahnschrift, sans-serif',
          fillColor: Cesium.Color.BLACK,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.TOP,
          pixelOffset: new Cesium.Cartesian2(0, -30),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          showBackground: true,
          backgroundColor: Cesium.Color.WHITE.withAlpha(0.85),
          backgroundPadding: new Cesium.Cartesian2(8, 4)
        }
      });
    });
    fixpunkteLoaded = true;
  } catch (err) {
    console.error("Fehler beim Laden der Fixpunkte:", err);
  }
}

function hideFixpunkteLayer() {
  fixpunkteEntities.forEach(e => e.show = false);
}


// Checkbox-Handler für Fixpunkte

document.addEventListener('DOMContentLoaded', function() {
  const chkFixpunkte = document.getElementById('chkFixpunkte');
  function setupFixpunkteHandler() {
    if (!chkFixpunkte || !window.viewer) return;
    chkFixpunkte.addEventListener('change', async (e) => {
      if (e.target.checked) {
        await loadFixpunkteLayer(window.viewer);
      } else {
        hideFixpunkteLayer();
      }
    });
    // Layer wird erst beim User-Klick geladen, nicht automatisch beim Laden
  }
  // Falls viewer schon da, sofort verbinden, sonst auf window.viewer warten
  if (window.viewer) {
    setupFixpunkteHandler();
  } else {
    // Warten bis viewer gesetzt ist
    let checkInterval = setInterval(() => {
      if (window.viewer) {
        clearInterval(checkInterval);
        setupFixpunkteHandler();
      }
    }, 100);
  }
});

// Exportiere die Initialisierung für app.js
window.initFixpunkteLayer = loadFixpunkteLayer;

function getGeoServerOwsUrl() {
  const protocol = window.location?.protocol || 'http:';

  // If the app is served on port 80 (or default), prefer same-origin reverse proxy.
  // This works with the nginx rule: /geoserver/ -> geoserver:8080/geoserver/
  const port = window.location?.port;
  if (port === '' || port === '80' || typeof port === 'undefined') {
    const host = window.location?.host || 'localhost';
    return `${protocol}//${host}/geoserver/ows`;
  }

  // Otherwise, use the IP/hostname from globals.js (or fall back to current hostname)
  const host = window.LOCAL_IP || window.location?.hostname || 'localhost';
  return `${protocol}//${host}:8081/geoserver/ows`;
}

const GEOSERVER_OWS_URL = getGeoServerOwsUrl();
/**
 * @file tools/layers.js
 * Basiskarten-Provider und Layer-Switcher.
 */

/**
 * Erzeugt Factory-Methoden für verfügbare Basiskarten.
 * @returns {Object<string,Function|null>} Mapping von Key -> ImageryProvider-Factory
 */
function createBaseLayerFactories() {
  return {
    muttenz: () => {
      // Rückgabe als Array: [10cm Layer, 200cm Layer (Fallback)]
      return [
        new Cesium.WebMapServiceImageryProvider({
          url: GEOSERVER_OWS_URL,
          layers: "FHNW:ortho_10cm",
          parameters: {
            service: "WMS",
            version: "1.3.0",
            request: "GetMap",
            styles: "",
            format: "image/png",
            transparent: true,
          },
          tilingScheme: new Cesium.WebMercatorTilingScheme(),
        }),
        new Cesium.WebMapServiceImageryProvider({
          url: GEOSERVER_OWS_URL,
          layers: "FHNW:ortho_200cm",
          parameters: {
            service: "WMS",
            version: "1.3.0",
            request: "GetMap",
            styles: "",
            format: "image/jpeg",
            transparent: false,
          },
          tilingScheme: new Cesium.WebMercatorTilingScheme(),
        }),
      ];
    },

    "pixelkarte-farbe": () =>
      new Cesium.WebMapServiceImageryProvider({
        url: "https://wms.geo.admin.ch/",
        layers: "ch.swisstopo.pixelkarte-farbe",
        parameters: {
          service: "WMS",
          version: "1.3.0",
          request: "GetMap",
          styles: "",
          format: "image/jpeg",
          transparent: false,
        },
        tilingScheme: new Cesium.WebMercatorTilingScheme(),
      }),

    // ?? Dummy-Eintrag nur, damit der Key existiert – Provider wird nicht benutzt
    "terrain-gray": null,
  };
}

/**
 * Initialisiert den Layer-Switcher (Radio-Buttons) und setzt den Startlayer.
 * @param {Cesium.Viewer} viewer Cesium Viewer
 */
function initBaseLayerSwitcher(viewer) {
  const factories = createBaseLayerFactories();

  // --- Overlay: FHNW Ortho 5cm (WMS) ---
  let orthoFhnw5cmImageryLayer = null;
  const chkOrthoFHNW = document.getElementById('chkOrthoFHNW');

  function createOrthoFhnw5cmProvider() {
    return new Cesium.WebMapServiceImageryProvider({
      url: GEOSERVER_OWS_URL,
      layers: "FHNW:FHNW_ortho_5cm",
      parameters: {
        service: "WMS",
        version: "1.3.0",
        request: "GetMap",
        styles: "",
        format: "image/png",
        transparent: true,
      },
      tilingScheme: new Cesium.WebMercatorTilingScheme(),
    });
  }

  function setOrthoFhnw5cmEnabled(enabled) {
    if (!enabled) {
      if (orthoFhnw5cmImageryLayer) {
        viewer.imageryLayers.remove(orthoFhnw5cmImageryLayer, true);
        orthoFhnw5cmImageryLayer = null;
      }
      return;
    }

    // Ensure it is present (always added above the baselayer)
    if (!orthoFhnw5cmImageryLayer) {
      const provider = createOrthoFhnw5cmProvider();
      orthoFhnw5cmImageryLayer = viewer.imageryLayers.addImageryProvider(provider);
      orthoFhnw5cmImageryLayer.alpha = 1.0;
    }
  }

  function syncOverlays() {
    setOrthoFhnw5cmEnabled(!!(chkOrthoFHNW && chkOrthoFHNW.checked));
  }

  function setBaseLayer(key) {
    // Entfernt alle vorhandenen Imagery-Layers
    viewer.imageryLayers.removeAll();
    // Overlays were removed as well; re-create them if enabled
    orthoFhnw5cmImageryLayer = null;

    if (key === "terrain-gray") {
      // Nur Terrain in Grau, keine Basiskarte
      const gray = Cesium.Color.fromCssColorString("#c8c8c8");
      viewer.scene.globe.baseColor = gray;
      viewer.scene.backgroundColor = gray;

      syncOverlays();
      return;
    }

    // Für andere Keys: Hintergrund wieder neutral setzen
    const neutral = Cesium.Color.fromCssColorString("#d3d3d3");
    viewer.scene.globe.baseColor = neutral;
    viewer.scene.backgroundColor = neutral;

    if (!factories[key]) return;
    const providers = factories[key]();
    
    // Unterstütze sowohl einzelne Provider als auch Arrays
    const providerArray = Array.isArray(providers) ? providers : [providers];
    
    // Füge alle Provider hinzu (in umgekehrter Reihenfolge, damit der erste oben liegt)
    providerArray.reverse().forEach((provider, index) => {
      const layer = viewer.imageryLayers.addImageryProvider(provider);
      
      // Für Muttenz: Setze Transparenz für den 200cm Layer (unterster Layer)
      if (key === 'muttenz' && index === 0) {
        layer.alpha = 0.7;
      }
    });

    syncOverlays();
  }

  // Startlayer: Muttenz
  setBaseLayer("muttenz");

  if (chkOrthoFHNW) {
    chkOrthoFHNW.addEventListener('change', () => {
      syncOverlays();
    });
  }

  // Event Listener für Radio Buttons
  const baselayerRadios = document.querySelectorAll('input[name="baselayer"]');
  baselayerRadios.forEach(radio => {
    radio.addEventListener('change', (e) => {
      if (e.target.checked) {
        setBaseLayer(e.target.value);
      }
    });
  });
}
