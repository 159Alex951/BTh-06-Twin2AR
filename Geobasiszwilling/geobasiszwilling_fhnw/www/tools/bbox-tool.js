/**
 * bbox-tool.js
 * =============================================================================
 * Bounding Box Zeichen-Tool für Cesium Viewer
 * - User klickt zwei Punkte (Ecken eines Rechtecks)
 * - Zeichnet visualisierte Bounding Box auf dem Terrain
 * - Gibt Koordinaten zurück (für Export etc.)
 * =============================================================================
 */

class BoundingBoxTool {
  constructor(viewer) {
    this.viewer = viewer;
    this.isActive = false;
    this.points = [];
    this.entity = null;
    this.tempEntities = []; // Für temporäre Marker und Linien
    this.previewEntity = null; // Live-Vorschau Box
    this.previewLine = null; // Live-Vorschau Linie
    this.handler = null;
    this.onComplete = null;
    this.previewPending = false; // RAF throttling
    this.lastMousePosition = null; // Letzte Mausposition für RAF
    this.boxHeight = 100; // Standard Box-Höhe (oben), unten immer -50m
  }

  /**
   * Aktiviert das Bounding Box Zeichen-Tool
   * @param {Function} callback - Wird aufgerufen wenn Box fertig ist: callback({west, south, east, north, min, max})
   */
  activate(callback) {
    if (this.isActive) return;
    
    this.isActive = true;
    this.points = [];
    this.onComplete = callback;
    
    // Cursor ändern
    this.viewer.canvas.style.cursor = 'crosshair';
    
    // Click Handler registrieren
    this.handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
    
    this.handler.setInputAction((click) => {
      // Hole Position vom Terrain/Tileset (nicht vom Ellipsoid!)
      const ray = this.viewer.camera.getPickRay(click.position);
      const cartesian = this.viewer.scene.globe.pick(ray, this.viewer.scene);
      
      if (!cartesian) {
        return;
      }
      
      this.points.push(cartesian);
      
      if (this.points.length === 1) {
        // Erster Punkt: zeige Marker
        this.showFirstPoint(cartesian);
      } else if (this.points.length === 2) {
        // Zweiter Punkt: zeige Linie
        this.showSecondPoint(cartesian);
      } else if (this.points.length === 3) {
        // Dritter Punkt: erstelle Box rechtwinklig
        this.drawRotatedBox();
        this.complete();
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    
    // Mouse Move für Live-Vorschau (Throttle für bessere Performance)
    let lastUpdate = 0;
    this.handler.setInputAction((movement) => {
      const now = performance.now();
      if (now - lastUpdate < 33) return; // Max 30fps
      lastUpdate = now;
      
      const ray = this.viewer.camera.getPickRay(movement.endPosition);
      const cartesian = this.viewer.scene.globe.pick(ray, this.viewer.scene);
      
      if (cartesian) {
        if (this.points.length === 1) {
          // Preview für Linie von P1 zur Mausposition
          this.showLinePreview(cartesian);
        } else if (this.points.length === 2) {
          // Preview für Box
          this.showLivePreview(cartesian);
        }
      }
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    
    // ESC zum Abbrechen
    this.handler.setInputAction(() => {
      this.cancel();
    }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
  }

  /**
   * Zeigt den ersten Punkt als Marker
   */
  showFirstPoint(cartesian) {
    if (this.entity) {
      this.viewer.entities.remove(this.entity);
    }
    
    this.entity = this.viewer.entities.add({
      position: cartesian,
      point: {
        pixelSize: 10,
        color: Cesium.Color.CYAN,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2
      }
    });
    this.tempEntities.push(this.entity);
  }

  /**
   * Zeigt den zweiten Punkt als Marker und Linie von P1 zu P2
   */
  showSecondPoint(cartesian) {
    // Entferne Preview-Linie
    if (this.previewLine) {
      this.viewer.entities.remove(this.previewLine);
      this.previewLine = null;
    }
    
    // Entferne alten Marker
    if (this.entity) {
      this.viewer.entities.remove(this.entity);
    }
    
    // Zeige beide Punkte
    const point1Entity = this.viewer.entities.add({
      position: this.points[0],
      point: {
        pixelSize: 10,
        color: Cesium.Color.CYAN,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2
      }
    });
    this.tempEntities.push(point1Entity);
    
    const point2Entity = this.viewer.entities.add({
      position: cartesian,
      point: {
        pixelSize: 10,
        color: Cesium.Color.YELLOW,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2
      }
    });
    this.tempEntities.push(point2Entity);
    
    // Zeige Linie von P1 zu P2
    this.entity = this.viewer.entities.add({
      polyline: {
        positions: [this.points[0], cartesian],
        width: 3,
        material: Cesium.Color.CYAN,
        clampToGround: true
      }
    });
    this.tempEntities.push(this.entity);
  }

  /**
   * Zeigt Live-Vorschau der Linie von P1 zur Mausposition
   */
  showLinePreview(mousePosition) {
    const point1 = this.points[0];
    
    // Update oder erstelle Preview-Linie
    if (this.previewLine) {
      this.previewLine.polyline.positions = [point1, mousePosition];
    } else {
      this.previewLine = this.viewer.entities.add({
        polyline: {
          positions: [point1, mousePosition],
          width: 2,
          material: Cesium.Color.YELLOW.withAlpha(0.6),
          clampToGround: true
        }
      });
    }
  }

  /**
   * Zeigt Live-Vorschau der Box während Mausbewegung nach Punkt 2
   * P1 und P2 sind FIXE ECKPUNKTE der Box-Längsseite
   * P3 (mousePosition) kann überall sein - wir berechnen die rechtwinklige Distanz zur P1-P2 Linie
   * und wenden diese Distanz rechtwinklig auf die gesamte P1-P2 Strecke an
   * Box steht horizontal im Raum (keine Verkippung), Höhe basiert auf P1
   */
  showLivePreview(mousePosition) {
    const point1 = this.points[0];
    const point2 = this.points[1];
    
    // Höhe von P1 für horizontale Box
    const carto1 = Cesium.Cartographic.fromCartesian(point1);
    const fixedHeight = carto1.height;
    
    // 1. Erstelle horizontale P1 und P2 auf gleicher Höhe
    const carto2 = Cesium.Cartographic.fromCartesian(point2);
    const point1Flat = Cesium.Cartesian3.fromRadians(carto1.longitude, carto1.latitude, fixedHeight);
    const point2Flat = Cesium.Cartesian3.fromRadians(carto2.longitude, carto2.latitude, fixedHeight);
    
    // 2. Längenvektor: P1 -> P2 (horizontal)
    const vec12 = Cesium.Cartesian3.subtract(point2Flat, point1Flat, new Cesium.Cartesian3());
    const length = Cesium.Cartesian3.magnitude(vec12);
    const vec12Norm = Cesium.Cartesian3.normalize(vec12, new Cesium.Cartesian3());
    
    // 3. Projiziere Mausposition auf die P1-P2 Linie (horizontal)
    const cartoMouse = Cesium.Cartographic.fromCartesian(mousePosition);
    const mouseFlat = Cesium.Cartesian3.fromRadians(cartoMouse.longitude, cartoMouse.latitude, fixedHeight);
    
    const vec1Mouse = Cesium.Cartesian3.subtract(mouseFlat, point1Flat, new Cesium.Cartesian3());
    const projectionLength = Cesium.Cartesian3.dot(vec1Mouse, vec12Norm);
    const projectedPoint = Cesium.Cartesian3.add(
      point1Flat,
      Cesium.Cartesian3.multiplyByScalar(vec12Norm, projectionLength, new Cesium.Cartesian3()),
      new Cesium.Cartesian3()
    );
    
    // 4. Breitenvektor: Rechtwinklig von der P1-P2 Linie (horizontal)
    const vecWidth = Cesium.Cartesian3.subtract(mouseFlat, projectedPoint, new Cesium.Cartesian3());
    const width = Cesium.Cartesian3.magnitude(vecWidth);
    
    if (width < 1) return; // Zu schmal
    
    // 5. Box-Center: Mittelpunkt von P1 nach P2, plus halber Breitenvektor (auf fixer Höhe)
    const midP1P2 = Cesium.Cartesian3.midpoint(point1Flat, point2Flat, new Cesium.Cartesian3());
    const centerCartesian = Cesium.Cartesian3.add(
      midP1P2,
      Cesium.Cartesian3.multiplyByScalar(vecWidth, 0.5, new Cesium.Cartesian3()),
      new Cesium.Cartesian3()
    );
    
    // 6. Berechne Orientierung mit East-North-Up Transformation (horizontal, keine Verkippung)
    const vecWidthNorm = Cesium.Cartesian3.normalize(vecWidth, new Cesium.Cartesian3());
    
    // East-North-Up Matrix am Center-Punkt
    const enuTransform = Cesium.Transforms.eastNorthUpToFixedFrame(centerCartesian);
    const enuMatrix = Cesium.Matrix4.getMatrix3(enuTransform, new Cesium.Matrix3());
    
    // Extrahiere East, North, Up Vektoren
    const east = Cesium.Matrix3.getColumn(enuMatrix, 0, new Cesium.Cartesian3());
    const north = Cesium.Matrix3.getColumn(enuMatrix, 1, new Cesium.Cartesian3());
    const up = Cesium.Matrix3.getColumn(enuMatrix, 2, new Cesium.Cartesian3());
    
    // Projiziere vec12 auf die horizontale Ebene (East-North)
    const vec12East = Cesium.Cartesian3.dot(vec12Norm, east);
    const vec12North = Cesium.Cartesian3.dot(vec12Norm, north);
    const xAxisHorizontal = Cesium.Cartesian3.normalize(
      Cesium.Cartesian3.add(
        Cesium.Cartesian3.multiplyByScalar(east, vec12East, new Cesium.Cartesian3()),
        Cesium.Cartesian3.multiplyByScalar(north, vec12North, new Cesium.Cartesian3()),
        new Cesium.Cartesian3()
      ),
      new Cesium.Cartesian3()
    );
    
    // Y-Achse: Kreuzprodukt von Up und X für perfekt horizontale Ausrichtung
    const yAxisHorizontal = Cesium.Cartesian3.cross(up, xAxisHorizontal, new Cesium.Cartesian3());
    Cesium.Cartesian3.normalize(yAxisHorizontal, yAxisHorizontal);
    
    // Erstelle Rotationsmatrix (horizontal ausgerichtet)
    const rotation = new Cesium.Matrix3(
      xAxisHorizontal.x, yAxisHorizontal.x, up.x,
      xAxisHorizontal.y, yAxisHorizontal.y, up.y,
      xAxisHorizontal.z, yAxisHorizontal.z, up.z
    );
    const orientation = Cesium.Quaternion.fromRotationMatrix(rotation);
    
    // 7. Update oder erstelle Preview-Entity
    const totalHeight = 50 + this.boxHeight; // 50m unten + boxHeight oben
    
    if (this.previewEntity) {
      this.previewEntity.position = centerCartesian;
      this.previewEntity.orientation = orientation;
      this.previewEntity.box.dimensions = new Cesium.Cartesian3(length, width, totalHeight);
    } else {
      this.previewEntity = this.viewer.entities.add({
        name: 'Preview Box',
        position: centerCartesian,
        orientation: orientation,
        box: {
          dimensions: new Cesium.Cartesian3(length, width, totalHeight),
          material: Cesium.Color.YELLOW.withAlpha(0.2),
          outline: true,
          outlineColor: Cesium.Color.YELLOW.withAlpha(0.6),
          outlineWidth: 2
        }
      });
    }
  }

  /**
   * Zeichnet die gedrehte 3D-Box
   * P1 und P2 sind FIXE ECKPUNKTE der Box-Längsseite
   * P3 kann überall sein - wir berechnen die rechtwinklige Distanz zur P1-P2 Linie
   * und wenden diese Distanz rechtwinklig auf die gesamte P1-P2 Strecke an
   * Box steht horizontal im Raum (keine Verkippung), Höhe basiert auf P1
   */
  drawRotatedBox() {
    const point1 = this.points[0];
    const point2 = this.points[1];
    const point3 = this.points[2];
    
    // Konvertiere zu Cartographic für Höhenberechnung
    const carto1 = Cesium.Cartographic.fromCartesian(point1);
    const carto2 = Cesium.Cartographic.fromCartesian(point2);
    
    // Höhe basiert auf Punkt 1: -50m bis +100m
    const baseHeight = carto1.height;
    const minHeight = baseHeight - 50;
    const maxHeight = baseHeight + 100;
    
    // 1. Erstelle horizontale P1 und P2 auf gleicher Höhe (baseHeight)
    const point1Flat = Cesium.Cartesian3.fromRadians(carto1.longitude, carto1.latitude, baseHeight);
    const point2Flat = Cesium.Cartesian3.fromRadians(carto2.longitude, carto2.latitude, baseHeight);
    
    // 2. Längenvektor: P1 -> P2 (horizontal)
    const vec12 = Cesium.Cartesian3.subtract(point2Flat, point1Flat, new Cesium.Cartesian3());
    const length = Cesium.Cartesian3.magnitude(vec12);
    const vec12Norm = Cesium.Cartesian3.normalize(vec12, new Cesium.Cartesian3());
    
    // 3. Projiziere P3 auf die P1-P2 Linie (horizontal)
    const carto3 = Cesium.Cartographic.fromCartesian(point3);
    const point3Flat = Cesium.Cartesian3.fromRadians(carto3.longitude, carto3.latitude, baseHeight);
    
    const vec13 = Cesium.Cartesian3.subtract(point3Flat, point1Flat, new Cesium.Cartesian3());
    const projectionLength = Cesium.Cartesian3.dot(vec13, vec12Norm);
    const projectedPoint = Cesium.Cartesian3.add(
      point1Flat,
      Cesium.Cartesian3.multiplyByScalar(vec12Norm, projectionLength, new Cesium.Cartesian3()),
      new Cesium.Cartesian3()
    );
    
    // 4. Breitenvektor: Rechtwinklig von der P1-P2 Linie zu P3 (horizontal)
    const vecWidth = Cesium.Cartesian3.subtract(point3Flat, projectedPoint, new Cesium.Cartesian3());
    const width = Cesium.Cartesian3.magnitude(vecWidth);

    // 4b. Corner footprint (horizontal) for export queries (WGS84)
    const corner1 = point1Flat;
    const corner2 = point2Flat;
    const corner3 = Cesium.Cartesian3.add(point2Flat, vecWidth, new Cesium.Cartesian3());
    const corner4 = Cesium.Cartesian3.add(point1Flat, vecWidth, new Cesium.Cartesian3());

    const cornersCarto = [corner1, corner2, corner3, corner4].map((c) => Cesium.Cartographic.fromCartesian(c));
    const cornersLonLat = cornersCarto.map((c) => [
      Cesium.Math.toDegrees(c.longitude),
      Cesium.Math.toDegrees(c.latitude),
    ]);

    const lons = cornersLonLat.map((p) => p[0]);
    const lats = cornersLonLat.map((p) => p[1]);
    const westDeg = Math.min(...lons);
    const eastDeg = Math.max(...lons);
    const southDeg = Math.min(...lats);
    const northDeg = Math.max(...lats);
    
    // 5. Box-Center: Mittelpunkt von P1 nach P2, plus halber Breitenvektor (auf baseHeight)
    const midP1P2 = Cesium.Cartesian3.midpoint(point1Flat, point2Flat, new Cesium.Cartesian3());
    const centerCartesian = Cesium.Cartesian3.add(
      midP1P2,
      Cesium.Cartesian3.multiplyByScalar(vecWidth, 0.5, new Cesium.Cartesian3()),
      new Cesium.Cartesian3()
    );
    
    // 6. Berechne Orientierung mit East-North-Up Transformation (horizontal, keine Verkippung)
    const vecWidthNorm = Cesium.Cartesian3.normalize(vecWidth, new Cesium.Cartesian3());
    
    // East-North-Up Matrix am Center-Punkt
    const enuTransform = Cesium.Transforms.eastNorthUpToFixedFrame(centerCartesian);
    const enuMatrix = Cesium.Matrix4.getMatrix3(enuTransform, new Cesium.Matrix3());
    
    // Extrahiere East, North, Up Vektoren
    const east = Cesium.Matrix3.getColumn(enuMatrix, 0, new Cesium.Cartesian3());
    const north = Cesium.Matrix3.getColumn(enuMatrix, 1, new Cesium.Cartesian3());
    const up = Cesium.Matrix3.getColumn(enuMatrix, 2, new Cesium.Cartesian3());
    
    // Projiziere vec12 auf die horizontale Ebene (East-North)
    const vec12East = Cesium.Cartesian3.dot(vec12Norm, east);
    const vec12North = Cesium.Cartesian3.dot(vec12Norm, north);
    const xAxisHorizontal = Cesium.Cartesian3.normalize(
      Cesium.Cartesian3.add(
        Cesium.Cartesian3.multiplyByScalar(east, vec12East, new Cesium.Cartesian3()),
        Cesium.Cartesian3.multiplyByScalar(north, vec12North, new Cesium.Cartesian3()),
        new Cesium.Cartesian3()
      ),
      new Cesium.Cartesian3()
    );
    
    // Y-Achse: Kreuzprodukt von Up und X für perfekt horizontale Ausrichtung
    const yAxisHorizontal = Cesium.Cartesian3.cross(up, xAxisHorizontal, new Cesium.Cartesian3());
    Cesium.Cartesian3.normalize(yAxisHorizontal, yAxisHorizontal);
    
    // Erstelle Rotationsmatrix (horizontal ausgerichtet)
    const rotation = new Cesium.Matrix3(
      xAxisHorizontal.x, yAxisHorizontal.x, up.x,
      xAxisHorizontal.y, yAxisHorizontal.y, up.y,
      xAxisHorizontal.z, yAxisHorizontal.z, up.z
    );
    const orientation = Cesium.Quaternion.fromRotationMatrix(rotation);
    
    // Entferne alte Entities
    if (this.entity) {
      this.viewer.entities.remove(this.entity);
    }
    
    // Entferne Vorschau
    if (this.previewEntity) {
      this.viewer.entities.remove(this.previewEntity);
      this.previewEntity = null;
    }
    
    // Entferne temporäre Marker und Linien
    this.tempEntities.forEach(entity => {
      this.viewer.entities.remove(entity);
    });
    this.tempEntities = [];
    
    // Erstelle gedrehte Box mit dynamischer Höhe
    const totalHeight = 50 + this.boxHeight; // 50m unten + boxHeight oben
    
    this.entity = this.viewer.entities.add({
      name: 'Bounding Box',
      position: centerCartesian,
      orientation: orientation,
      box: {
        dimensions: new Cesium.Cartesian3(length, width, totalHeight),
        material: Cesium.Color.CYAN.withAlpha(0.3),
        outline: true,
        outlineColor: Cesium.Color.CYAN,
        outlineWidth: 2
      }
    });
    
    // Speichere Bounds (benötigt centerCarto)
    const centerCarto = Cesium.Cartographic.fromCartesian(centerCartesian);
    this.bounds = {
      center: {
        longitude: Cesium.Math.toDegrees(centerCarto.longitude),
        latitude: Cesium.Math.toDegrees(centerCarto.latitude),
        height: baseHeight + (totalHeight / 2) - 50 // Mitte der Box
      },
      dimensions: {
        length: length,
        width: width,
        height: totalHeight
      },
      minHeight: minHeight,
      maxHeight: baseHeight + this.boxHeight,
      // Axis-aligned bbox in WGS84 degrees (contains the rotated footprint)
      west: westDeg,
      south: southDeg,
      east: eastDeg,
      north: northDeg,
      // Rotated footprint polygon corners (WGS84 degrees)
      footprint: cornersLonLat
    };
  }

  /**
   * Beendet das Tool und gibt Ergebnis zurück
   */
  complete() {
    this.isActive = false;
    this.viewer.canvas.style.cursor = 'default';
    
    if (this.handler) {
      this.handler.destroy();
      this.handler = null;
    }
    
    console.log('[BBoxTool] Bounding Box erstellt:', this.bounds);
    
    if (this.onComplete && this.bounds) {
      this.onComplete(this.bounds);
    }
  }

  /**
   * Bricht das Tool ab
   */
  cancel() {
    this.isActive = false;
    this.points = [];
    this.viewer.canvas.style.cursor = 'default';
    
    if (this.handler) {
      this.handler.destroy();
      this.handler = null;
    }
    
    if (this.entity) {
      this.viewer.entities.remove(this.entity);
      this.entity = null;
    }
    
    if (this.previewLine) {
      this.viewer.entities.remove(this.previewLine);
      this.previewLine = null;
    }
    
    if (this.previewEntity) {
      this.viewer.entities.remove(this.previewEntity);
      this.previewEntity = null;
    }
    
    console.log('[BBoxTool] Abgebrochen');
  }

  /**
   * Entfernt die gezeichnete Box
   */
  clear() {
    if (this.entity) {
      this.viewer.entities.remove(this.entity);
      this.entity = null;
    }
    
    if (this.previewLine) {
      this.viewer.entities.remove(this.previewLine);
      this.previewLine = null;
    }
    
    if (this.previewEntity) {
      this.viewer.entities.remove(this.previewEntity);
      this.previewEntity = null;
    }
    
    this.bounds = null;
    this.points = [];
  }

  /**
   * Gibt die aktuellen Bounds zurück
   */
  getBounds() {
    return this.bounds;
  }

  /**
   * Setzt die Box-Höhe und aktualisiert die Box falls sie existiert
   */
  setBoxHeight(height) {
    this.boxHeight = height;
    
    // Aktualisiere existierende Box
    if (this.entity && this.points.length === 3) {
      const totalHeight = 50 + this.boxHeight;
      this.entity.box.dimensions = new Cesium.Cartesian3(
        this.entity.box.dimensions.getValue().x,
        this.entity.box.dimensions.getValue().y,
        totalHeight
      );
      
      // Aktualisiere bounds
      if (this.bounds) {
        const carto1 = Cesium.Cartographic.fromCartesian(this.points[0]);
        const baseHeight = carto1.height;
        
        this.bounds.dimensions.height = totalHeight;
        this.bounds.minHeight = baseHeight - 50;
        this.bounds.maxHeight = baseHeight + this.boxHeight;
        this.bounds.center.height = baseHeight + (totalHeight / 2) - 50;
      }
    }
    
    // Aktualisiere Preview falls aktiv
    if (this.previewEntity && this.points.length === 2) {
      const totalHeight = 50 + this.boxHeight;
      this.previewEntity.box.dimensions = new Cesium.Cartesian3(
        this.previewEntity.box.dimensions.getValue().x,
        this.previewEntity.box.dimensions.getValue().y,
        totalHeight
      );
    }
  }

  /**
   * Prüft ob ein Punkt innerhalb der Bounding Box liegt
   */
  containsPoint(longitude, latitude) {
    if (!this.bounds) return false;
    
    return longitude >= this.bounds.west &&
           longitude <= this.bounds.east &&
           latitude >= this.bounds.south &&
           latitude <= this.bounds.north;
  }

  /**
   * Prüft ob ein Tileset innerhalb der Bounding Box liegt
   */
  async getTilesInBounds(tileset) {
    if (!this.bounds || !tileset) return [];
    
    const tilesInBounds = [];
    const rectangle = this.bounds.rectangle;
    
    // Durchlaufe alle Tiles im Tileset
    const traverse = (tile) => {
      if (!tile) return;
      
      // Prüfe ob Tile BoundingVolume die Box schneidet
      if (tile.boundingVolume) {
        const tileRect = tile.boundingVolume.rectangle;
        
        if (tileRect && Cesium.Rectangle.intersection(tileRect, rectangle)) {
          tilesInBounds.push(tile);
        }
      }
      
      // Rekursiv durch Kinder
      if (tile.children) {
        tile.children.forEach(child => traverse(child));
      }
    };
    
    traverse(tileset.root);
    
    return tilesInBounds;
  }
}

// Export für Verwendung in anderen Modulen
if (typeof module !== 'undefined' && module.exports) {
  module.exports = BoundingBoxTool;
}
