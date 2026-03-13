/**
 * @file tools/infofenster.js
 * Initialisiert das benutzerdefinierte Info-Panel für Gebäude.
 * Lädt bei Bedarf das Baujahr über die BFS-API nach und registriert Picking.
 */

/**
 * Initialisiert das Infofenster-Subsystem und registriert Picking-Handler.
 * @param {Cesium.Viewer} viewer Cesium Viewer
 */
function infofenster(viewer) {
  if (!viewer) return;

  const infoBoxEl = document.getElementById("infoBox");
  const infoTitleEl = document.getElementById("infoTitle");
  const infoContentEl = document.getElementById("infoContent");
  const infoCloseEl = document.getElementById("infoClose");
  const headerEl = infoBoxEl ? infoBoxEl.querySelector('.info-header') : null;
  const floorCache = {};

  /**
  * Formatiert eine Zahl als Meter-String, ansonsten '-' bei ungültigen Werten.
   * @param {*} value
   * @returns {string}
   */
  function formatMeters(value) {
    if (value === null || value === undefined || value === "") return "-";
    const n = parseFloat(value);
    if (isNaN(n)) return String(value);
    return n.toFixed(2) + " m";
  }

  /**
  * Sicherer Text-Formatter: gibt '-' für leere/undefinierte Werte zurück.
   * @param {*} value
   * @returns {string}
   */
  function safeText(value) {
    if (value === null || value === undefined || value === "") return "-";
    return String(value);
  }

  /**
  * Öffnet das Infofenster. Optional kann eine Screen-Position übergeben werden.
   * @param {string} title
   * @param {string} tableHtml
   * @param {{x:number,y:number}} [pos]
   */
  function showInfoWindow(title, tableHtml, pos) {
    if (!infoBoxEl || !infoTitleEl || !infoContentEl) return;
    infoTitleEl.textContent = title || "Gebaeudeinfo";
    infoContentEl.innerHTML = tableHtml;
    // Öffnen, damit Dimensionen verfügbar werden
    infoBoxEl.classList.add("open");

    if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
      // Positioniere nahe dem Klick, clamped an Viewport
      const offset = 10;
      infoBoxEl.style.right = 'auto';
      const width = infoBoxEl.offsetWidth;
      const height = infoBoxEl.offsetHeight;

      let left = pos.x + offset;
      let top = pos.y - height - offset;

      if (top < 8) top = pos.y + offset; // Bei wenig Platz unterhalb positionieren
      if (left + width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - width - 8);
      if (top + height > window.innerHeight - 8) top = Math.max(8, window.innerHeight - height - 8);

      infoBoxEl.style.left = left + 'px';
      infoBoxEl.style.top = top + 'px';
    }
  }

  /** Schliesst das Infofenster. */
  function hideInfoWindow() {
    if (infoBoxEl) infoBoxEl.classList.remove("open");

    // Auswahl/Highlight zurücksetzen
    if (window.selectedBuildingEgid !== undefined) {
      delete window.selectedBuildingEgid;
      if (typeof window.updateBFSStyle === "function") {
        try { window.updateBFSStyle(); } catch (_) { }
      }
    }
  }

  if (infoCloseEl) infoCloseEl.addEventListener("click", hideInfoWindow);

  // Dragging für das Infofenster (Header)
  if (headerEl && infoBoxEl) {
    let isDragging = false;
    let dragOffsetX = 0;
    let dragOffsetY = 0;

    headerEl.addEventListener('pointerdown', function (e) {
      if (e.target === infoCloseEl) return;
      isDragging = true;
      const rect = infoBoxEl.getBoundingClientRect();
      dragOffsetX = e.clientX - rect.left;
      dragOffsetY = e.clientY - rect.top;
      infoBoxEl.style.right = 'auto';
      infoBoxEl.style.left = rect.left + 'px';
      infoBoxEl.style.top = rect.top + 'px';
      if (headerEl.setPointerCapture) {
        try { headerEl.setPointerCapture(e.pointerId); } catch (_) { }
      }
      e.preventDefault();
    });

    document.addEventListener('pointermove', function (e) {
      if (!isDragging) return;
      let left = e.clientX - dragOffsetX;
      let top = e.clientY - dragOffsetY;
      left = Math.max(0, Math.min(left, window.innerWidth - infoBoxEl.offsetWidth));
      top = Math.max(0, Math.min(top, window.innerHeight - infoBoxEl.offsetHeight));
      infoBoxEl.style.left = left + 'px';
      infoBoxEl.style.top = top + 'px';
    });

    document.addEventListener('pointerup', function (e) {
      if (!isDragging) return;
      isDragging = false;
      if (headerEl.releasePointerCapture) {
        try { headerEl.releasePointerCapture(e.pointerId); } catch (_) { }
      }
    });
  }

  /**
  * Lädt das Baujahr (falls vorhanden) über die GeoAdmin/BFS-API und schreibt es in die Zelle.
   * @param {string} egid
   */
  function fetchBaujahrForEgid(egid) {
    const cell = document.getElementById("baujahrCell");
    if (!cell || !egid || egid === "-") return;

    cell.textContent = "lade...";
    // Stable JSON endpoint (per-EGID)
    const url = `https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/${egid}_0?f=json&lang=de`;

    fetch(url)
      .then((resp) => {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        return resp.json();
      })
      .then((data) => {
        // JSON usually provides attributes under 'attributes' or 'properties'
        const attrs = (data && (data.attributes || data.properties)) || (data && data.feature && data.feature.attributes) || null;
        let year = null;
        const floors = attrs.gastw ?? null;
        floorCache[egid] = floors;
        console.log("EGID", egid, "Anzahl Stockwerke (gastw) =", floors);
        if (attrs) {
          // Prefer 'GBAUJ' variants if present
          const keys = Object.keys(attrs);
          const gbKey = keys.find(k => /^g?bauj(ahr)?$/i.test(k));
          if (gbKey) {
            year = attrs[gbKey];
          } else {
            // common keys fallback
            year = attrs.BAUJAHR || attrs.baujahr || attrs.Baujahr || null;
            if (!year) {
              const anyKey = keys.find(k => /bau/i.test(k));
              if (anyKey) year = attrs[anyKey];
            }
          }
        }

        // Fallback: any 4-digit year in JSON
        if (!year) {
          try {
            const txt = JSON.stringify(data);
            const m = txt.match(/\b(17|18|19|20)\d{2}\b/);
            if (m) year = m[0];
          } catch (e) { /* ignore */ }
        }

        cell.textContent = year ? String(year) : "-";
      })
      .catch((err) => {
        console.warn("Fehler beim Laden Baujahr (JSON):", err);
        cell.textContent = "-";
      });
  }

  // Feature-Picking (Linksklick)
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

  handler.setInputAction(function (movement) {
    console.log("Infofenster click handler triggered", movement);

    const picked = viewer.scene.pick(movement.position);
    console.log("Picked raw:", picked);

    if (!Cesium.defined(picked)) {
      hideInfoWindow();
      return;
    }

    const isTilesFeature = typeof picked.getProperty === "function";
    const isProjectedEntity =
      picked.id &&
      picked.id.properties &&
      (picked.id.properties.GWR_EGID !== undefined);

    console.log("isTilesFeature", isTilesFeature, "isProjectedEntity", isProjectedEntity);

    // 1) BFS 3D Tiles branch
    if (isTilesFeature) {
      const rawEgid = picked.getProperty("egid");
      if (rawEgid !== null && rawEgid !== undefined && rawEgid !== "") {
        window.selectedBuildingEgid = String(rawEgid);
        if (typeof window.updateBFSStyle === "function") {
          try { window.updateBFSStyle(); } catch (_) { }
        }
      } else {
        if (window.selectedBuildingEgid !== undefined) {
          delete window.selectedBuildingEgid;
          if (typeof window.updateBFSStyle === "function") {
            try { window.updateBFSStyle(); } catch (_) { }
          }
        }
      }

      const egid = safeText(picked.getProperty("egid"));
      const objektart = safeText(picked.getProperty("objektart"));
      const baujahr = safeText(picked.getProperty("baujahr"));
      const strasse = safeText(picked.getProperty("strasse"));
      const hausnummer = safeText(picked.getProperty("hausnummer"));
      const plz = safeText(picked.getProperty("plz"));
      const gemeinde = safeText(picked.getProperty("gemeinde"));
      const dachMax = formatMeters(picked.getProperty("dach_max"));
      const gelaende = formatMeters(picked.getProperty("gelaendepunkt"));
      const anzahlWohnungen = safeText(picked.getProperty("anzahl_wohnungen"));

      const bfsUrl = (egid !== "-")
        ? 'https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/' + egid + '_0/extendedHtmlPopup?lang=de'
        : null;
      const linkHtml = bfsUrl ? '<a href="' + bfsUrl + '" target="_blank" rel="noopener">BFS-Eintrag</a>' : '-';

      const adresse = (strasse !== "-" && hausnummer !== "-") ? strasse + " " + hausnummer : "-";
      const ort = (plz !== "-" && gemeinde !== "-") ? plz + " " + gemeinde : (gemeinde !== "-" ? gemeinde : "-");

      const tableHtml =
        '<table class="info-table"><tbody>' +
        '<tr><th>EGID</th><td>' + egid + '</td></tr>' +
        '<tr><th>Objektart</th><td>' + objektart + '</td></tr>' +
        '<tr><th>Baujahr</th><td>' + baujahr + '</td></tr>' +
        '<tr><th>Adresse</th><td>' + adresse + '</td></tr>' +
        '<tr><th>Ort</th><td>' + ort + '</td></tr>' +
        '<tr><th>Wohnungen</th><td>' + anzahlWohnungen + '</td></tr>' +
        '<tr><th>Hoehe</th><td>' + dachMax + '</td></tr>' +
        '<tr><th>Gelaendepunkt</th><td>' + gelaende + '</td></tr>' +
        '<tr><th>Link</th><td>' + linkHtml + '</td></tr>' +
        '</tbody></table>';

      const title = egid !== "-" ? "Gebaeude " + egid : "Gebaeudeinfo";
      showInfoWindow(title, tableHtml, movement.position);

      // also fetch year/floors in background
      if (egid && egid !== "-") {
        fetchBaujahrForEgid(egid);
      }

      return;
    }

    // 2) Projected-entity branch
    if (isProjectedEntity) {
      const entity = picked.id;
      const props = entity.properties;

      const egidProp = props.GWR_EGID;
      const egidRaw = egidProp && egidProp.getValue ? egidProp.getValue() : egidProp;

      const egid = safeText(egidRaw);          // for display
      const egidKey = egidRaw;                 // for cache lookup, same type as in fetchBaujahrForEgid

      const objektartProp = props.Art;
      const objektart = safeText(objektartProp && objektartProp.getValue ? objektartProp.getValue() : objektartProp);

      const bfsNrProp = props.BFSNr;
      const bfsNr = safeText(bfsNrProp && bfsNrProp.getValue ? bfsNrProp.getValue() : bfsNrProp);

      const kantonProp = props.Kanton;
      const kanton = safeText(kantonProp && kantonProp.getValue ? kantonProp.getValue() : kantonProp);

      const qualitaetProp = props.Qualitaet;
      const qualitaet = safeText(qualitaetProp && qualitaetProp.getValue ? qualitaetProp.getValue() : qualitaetProp);

      const heightProp = props.height;
      const height = safeText(heightProp && heightProp.getValue ? heightProp.getValue() : heightProp);

      const bfsUrl = egid !== "-"
        ? 'https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/' + egid + '_0/extendedHtmlPopup?lang=de'
        : null;
      const linkHtml = bfsUrl ? '<a href="' + bfsUrl + '" target="_blank" rel="noopener">BFS-Eintrag</a>' : '-';

      const floorsText = safeText(floorCache[egidKey] ?? "-");

      const tableHtml =
        '<table class="info-table"><tbody>' +
        '<tr><th>EGID</th><td>' + egid + '</td></tr>' +
        '<tr><th>Objektart</th><td>' + objektart + '</td></tr>' +
        '<tr><th>BFSNr</th><td>' + bfsNr + '</td></tr>' +
        '<tr><th>Kanton</th><td>' + kanton + '</td></tr>' +
        '<tr><th>Qualitaet</th><td>' + qualitaet + '</td></tr>' +
        '<tr><th>Hoehe (dummy)</th><td>' + height + '</td></tr>' +
        '<tr><th>Anzahl Stockwerke</th><td>' + floorsText + '</td></tr>' +
        '<tr><th>Link</th><td>' + linkHtml + '</td></tr>' +
        '</tbody></table>';

      showInfoWindow('Projiziertes Gebaeude ' + egid, tableHtml, movement.position);

      if (egidKey && egidKey !== "-") {
        fetchBaujahrForEgid(egidKey);  // keeps filling floorCache as before
      }

      return;
    }

    // 3) Fallback: nothing relevant picked
    hideInfoWindow();
    return;
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);


  // Rechtsklick schliesst das Fenster
  handler.setInputAction(function () { hideInfoWindow(); }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
}

// Globale Sichtbarkeit, damit `app.js` die Funktion aufrufen kann
window.infofenster = infofenster;
