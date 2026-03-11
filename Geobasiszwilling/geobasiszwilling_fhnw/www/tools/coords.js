/**
 * @file tools/coords.js
 * Utilities zur Anzeige von Koordinaten (LV95 + H) und Konvertierung WGS84 -> LV95.
 */

// Schweizer Zahlenformat (mit 1'000-Trennzeichen)
const chf = new Intl.NumberFormat("de-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const chf0 = new Intl.NumberFormat("de-CH", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// Lokaler Höhen-Offset: Cesium -> m ü. M. (LHN95/LN02-Nähe)
const HEIGHT_OFFSET_M = -3.1; // <- DIESEN WERT ANPASSEN

/**
 * Wandelt WGS84 (lon,lat in degrees) nach LV95 (E,N) mittels Swisstopo-Formeln.
 * @param {number} lon
 * @param {number} lat
 * @returns {{E:number,N:number}}
 */
function wgs84toLv95(lon, lat) {
  const lat_sec = lat * 3600;
  const lon_sec = lon * 3600;

  const lat_aux = (lat_sec - 169028.66) / 10000;
  const lon_aux = (lon_sec - 26782.5) / 10000;

  const E =
    2600072.37 +
    211455.93 * lon_aux -
    10938.51 * lon_aux * lat_aux -
    0.36 * lon_aux * lat_aux * lat_aux -
    44.54 * lon_aux * lon_aux * lon_aux;

  const N =
    1200147.07 +
    308807.95 * lat_aux +
    3745.25 * lon_aux * lon_aux +
    76.63 * lat_aux * lat_aux -
    194.56 * lon_aux * lon_aux * lat_aux +
    119.79 * lat_aux * lat_aux * lat_aux;

  return { E, N };
}

/**
 * Initialisiert die Koordinatenanzeige im UI (LV95 + H) und registriert Mouse-Move Handler.
 * @param {Cesium.Viewer} viewer Cesium Viewer
 */
function initCoordinateDisplay(viewer) {
  const coordPanel = document.getElementById("coordPanel");
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

  handler.setInputAction((movement) => {
    const ray = viewer.camera.getPickRay(movement.endPosition);
    const cartesian = viewer.scene.globe.pick(ray, viewer.scene);

    if (!cartesian) {
      coordPanel.textContent = "E: -  |  N: -  |  H: -";
      return;
    }

    const c = Cesium.Cartographic.fromCartesian(cartesian);
    const lon = Cesium.Math.toDegrees(c.longitude);
    const lat = Cesium.Math.toDegrees(c.latitude);
    const heightEll = c.height; // ellipsoidische Höhe aus Cesium

    const { E, N } = wgs84toLv95(lon, lat);

    // Einfache Approximation auf Schweizer Höhensystem
    const heightCH = heightEll + HEIGHT_OFFSET_M;

    coordPanel.textContent =
      `E: ${chf.format(E)}  |  ` +
      `N: ${chf.format(N)}  |  ` +
      `H: ${chf0.format(heightCH)} m`;
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
}
