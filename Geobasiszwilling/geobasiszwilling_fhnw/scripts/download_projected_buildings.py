import json
import hashlib
import time
from pathlib import Path

import geopandas as gpd
import rasterio
import requests

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent if '__file__' in globals() else Path.cwd()
IMPORT_DIR = BASE_DIR / "import" / "proj"
TERRAIN_DIR = BASE_DIR / "import" / "terrain"
IMPORT_DIR.mkdir(parents=True, exist_ok=True)

WFS_URL = "https://geodienste.ch/db/av_0/deu"
WFS_PARAMS = {
    "SERVICE": "WFS",
    "VERSION": "2.0.0",
    "REQUEST": "GetFeature",
    "TYPENAMES": "ms:LCSFPROJ",
    "OUTPUTFORMAT": "application/json; subtype=geojson",
    "SRSNAME": "EPSG:4326",
    # optional bbox for tests; remove if full extent is needed
    # "BBOX": "47.351,7.477,47.711,7.797,urn:ogc:def:crs:EPSG::4326",
}

BFS_BASE = "https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/"

RAW_FILE = IMPORT_DIR / "projected_buildings_raw.geojson"
ENRICHED_FILE = IMPORT_DIR / "projected_buildings_enriched.geojson"
READY_FILE = IMPORT_DIR / "projected_buildings_2d_ready.gpkg"
EGID_CACHE_FILE = IMPORT_DIR / "egid_cache.json"

GSTAT_MAP = {
    1001: "Projektiert",
    1002: "Bewilligt",
    1003: "Im Bau",
    1004: "Bestehend",
    1005: "Nicht nutzbar",
    1007: "Abgebrochen",
    1008: "Nicht realisiert",
}

GKAT_MAP = {
    1010: "Provisorische Unterkunft",
    1020: "Gebäude mit ausschliesslicher Wohnnutzung",
    1030: "Andere Wohngebäude (Wohngebäude mit Nebennutzung)",
    1040: "Gebäude mit teilweiser Wohnnutzung",
    1060: "Gebäude ohne Wohnnutzung",
    1080: "Sonderbau",
}

GVOLSCE_SOURCE_MAP = {
    869: "Gemaess Baubewilligung",
    858: "Gemaess Gebaeudeenergieausweis der Kantone (GEAK)",
    853: "Gemaess Gebaeudeversicherung",
    852: "Gemaess amtlicher Schaetzung",
    857: "Gemaess Eigentuemer/in / Verwaltung",
    851: "Gemaess amtlicher Vermessung",
    870: "Gemaess topografischem Landschaftsmodell (TLM)",
    878: "Nicht bestimmbares Volumen (nicht geschlossenes Gebaeude)",
    859: "Andere",
}

# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def geometry_hash(geom) -> str:
    if geom is None or geom.is_empty:
        return ""
    return hashlib.sha1(geom.wkb).hexdigest()


def load_geojson(path: Path) -> dict:
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_geojson(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_egid_cache() -> dict:
    if not EGID_CACHE_FILE.exists():
        return {}
    with open(EGID_CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_egid_cache(cache: dict) -> None:
    with open(EGID_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def as_int_or_none(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------
# STEP 1: WFS DOWNLOAD + MERGE ONLY NEW GEOMETRIES
# ------------------------------------------------------------------
def download_wfs() -> dict:
    resp = requests.get(WFS_URL, params=WFS_PARAMS, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    data["features"] = [
        feat for feat in data.get("features", [])
        if (feat.get("properties") or {}).get("Art") == "Gebaeude"
    ]
    return data


def merge_new_features(new_data: dict) -> dict:
    existing_data = load_geojson(ENRICHED_FILE if ENRICHED_FILE.exists() else RAW_FILE)
    existing_features = existing_data.get("features", [])
    seen_hashes = set()

    for feat in existing_features:
        geom = feat.get("geometry")
        if geom:
            geom_hash = hashlib.sha1(json.dumps(geom, sort_keys=True).encode("utf-8")).hexdigest()
            seen_hashes.add(geom_hash)

    added = 0
    for feat in new_data.get("features", []):
        geom = feat.get("geometry")
        if not geom:
            continue
        geom_hash = hashlib.sha1(json.dumps(geom, sort_keys=True).encode("utf-8")).hexdigest()
        if geom_hash in seen_hashes:
            continue
        props = feat.get("properties") or {}
        props["geometry_hash"] = geom_hash
        feat["properties"] = props
        existing_features.append(feat)
        seen_hashes.add(geom_hash)
        added += 1

    merged = {
        "type": "FeatureCollection",
        "features": existing_features,
    }
    save_geojson(RAW_FILE, merged)
    print(f"Merged WFS features. Added {added} new geometries, total {len(existing_features)}.")
    return merged


# ------------------------------------------------------------------
# STEP 2: ENRICH ONLY NEW EGIDs
# ------------------------------------------------------------------
def fetch_attrs_for_egid(egid: str | int) -> dict:
    egid_str = str(egid)
    url = f"{BFS_BASE}{egid_str}_0?f=json&lang=de"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        attrs = (
            data.get("attributes")
            or data.get("properties")
            or (data.get("feature") or {}).get("attributes")
            or {}
        )

        gstat_code = as_int_or_none(attrs.get("gstat"))
        gkat_code = as_int_or_none(attrs.get("gkat"))
        gvolsce_code = as_int_or_none(attrs.get("gvolsce"))

        return {
            "gastw": attrs.get("gastw"),
            "strname_deinr": attrs.get("strname_deinr"),
            "ggdename": attrs.get("ggdename"),
            "lparz": attrs.get("lparz"),
            "gstat": gstat_code,
            "gstat_text": GSTAT_MAP.get(gstat_code),
            "gkat": gkat_code,
            "gkat_text": GKAT_MAP.get(gkat_code),
            "garea": attrs.get("garea"),
            "gvol": attrs.get("gvol"),
            "gebf": attrs.get("gebf"),
            "gvolsce": gvolsce_code,
            "gvolsce_text": GVOLSCE_SOURCE_MAP.get(gvolsce_code),
        }
    except Exception as e:
        print(f"EGID {egid_str}: error {e}")
        return {}


def enrich_features(data: dict) -> dict:
    cache = load_egid_cache()
    features = data.get("features", [])

    egids_to_fetch = set()
    for feat in features:
        props = feat.get("properties") or {}
        egid = props.get("GWR_EGID") or props.get("egid")
        if egid not in (None, "", "-"):
            egid_str = str(egid)
            if egid_str not in cache:
                egids_to_fetch.add(egid_str)

    if egids_to_fetch:
        print(f"Fetching {len(egids_to_fetch)} new EGIDs...")
    for idx, egid in enumerate(sorted(egids_to_fetch), start=1):
        cache[egid] = fetch_attrs_for_egid(egid)
        if idx % 20 == 0:
            save_egid_cache(cache)
        time.sleep(0.15)
    save_egid_cache(cache)

    for feat in features:
        props = feat.get("properties") or {}
        egid = props.get("GWR_EGID") or props.get("egid")
        extra = cache.get(str(egid), {}) if egid not in (None, "", "-") else {}
        props["gastw"] = extra.get("gastw")
        props["Adresse"] = extra.get("strname_deinr")
        props["Gemeinde"] = extra.get("ggdename")
        props["Parzellennummer"] = extra.get("lparz")
        props["gstat"] = extra.get("gstat")
        props["gstat_text"] = extra.get("gstat_text")
        props["gkat"] = extra.get("gkat")
        props["gkat_text"] = extra.get("gkat_text")
        props["garea"] = extra.get("garea")
        props["gvol"] = extra.get("gvol")
        props["gebf"] = extra.get("gebf")
        props["gvolsce"] = extra.get("gvolsce")
        props["gvolsce_text"] = extra.get("gvolsce_text")
        feat["properties"] = props

    enriched = {"type": "FeatureCollection", "features": features}
    save_geojson(ENRICHED_FILE, enriched)
    print(f"Saved enriched data to {ENRICHED_FILE}")
    return enriched


# ------------------------------------------------------------------
# STEP 3: IMPORT_PROJECTED_2D LOGIC WITHOUT OLD STATS PART
# ------------------------------------------------------------------
def build_hybrid_elevation_logic():
    tiff_files = list(TERRAIN_DIR.glob("*.tif"))
    tiff_bounds = []
    for tiff in tiff_files:
        try:
            with rasterio.open(tiff) as src:
                bounds = src.bounds
                tiff_bounds.append({
                    "path": tiff,
                    "left": bounds.left,
                    "right": bounds.right,
                    "bottom": bounds.bottom,
                    "top": bounds.top,
                })
        except Exception:
            continue
    return tiff_bounds


def get_elevation_hybrid(x, y, tiff_bounds):
    for tb in tiff_bounds:
        if tb["left"] <= x <= tb["right"] and tb["bottom"] <= y <= tb["top"]:
            try:
                with rasterio.open(tb["path"]) as src:
                    for val in src.sample([(x, y)]):
                        z_val = val[0]
                        if z_val != src.nodata and z_val > -500:
                            return float(z_val)
            except Exception:
                continue
    return 0.0


def process_waterfall_height(row):
    gvol = float(row.get("gvol", 0) or 0)
    garea = float(row.get("garea", 0) or 0)
    gastw = float(row.get("gastw", 0) or 0)
    gkat_raw = row.get("gkat", "")

    try:
        gkat = str(int(float(gkat_raw)))
    except (ValueError, TypeError):
        gkat = str(gkat_raw).strip()

    floor_mult = 3.0 if gkat == "1060" else 2.5
    raw_stw = (gastw * floor_mult) if gastw > 0 else None
    raw_vol = (gvol / garea) if (gvol > 0 and garea > 0) else None

    final_h = None
    source = None

    if raw_vol is not None:
        use_vol = raw_vol >= 2.0
        if use_vol and raw_stw is not None:
            diff_pct = abs(raw_vol - raw_stw) / raw_stw
            if gkat == "1060" and diff_pct > 2.0:
                use_vol = False
            elif gkat in ["1020", "1030", "1040"] and diff_pct > 1.0:
                use_vol = False
            elif gkat not in ["1060", "1020", "1030", "1040"] and diff_pct > 1.0:
                use_vol = False
        if use_vol:
            final_h = raw_vol
            source = "volume_math"

    if final_h is None and raw_stw is not None:
        final_h = raw_stw
        source = "floors_math"

    if final_h is None:
        if gkat == "1060":
            final_h = 9.0
            source = "category_fallback_1060"
        elif gkat == "1080":
            final_h = 0.0
            source = "ignore"
        else:
            final_h = 7.5
            source = "absolute_fallback"

    if gkat == "1080":
        final_h = 0.0
        source = "ignore"

    return final_h, source, raw_vol, raw_stw


def prepare_2d_ready():
    gdf = gpd.read_file(ENRICHED_FILE)
    if gdf.crs is not None and gdf.crs.to_epsg() != 2056:
        gdf = gdf.to_crs(epsg=2056)

    heights, sources, raw_vols, raw_stws = [], [], [], []
    for _, row in gdf.iterrows():
        h, source, raw_v, raw_s = process_waterfall_height(row)
        heights.append(h)
        sources.append(source)
        raw_vols.append(raw_v)
        raw_stws.append(raw_s)

    gdf["computed_height"] = heights
    gdf["height_source"] = sources
    gdf["height_raw_gvol"] = raw_vols
    gdf["height_raw_gastw"] = raw_stws
    gdf = gdf[gdf["height_source"] != "ignore"].copy()

    tiffs = build_hybrid_elevation_logic()
    z_bases = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            z_bases.append(0.0)
            continue
        try:
            if geom.geom_type == "Polygon":
                coords = list(geom.exterior.coords)
            elif geom.geom_type == "MultiPolygon":
                coords = list(geom.geoms[0].exterior.coords)
            else:
                coords = []
            corner_z = [get_elevation_hybrid(x, y, tiffs) for x, y in coords]
            corner_z = [z for z in corner_z if z > 0]
            z_bases.append(min(corner_z) if corner_z else 0.0)
        except Exception:
            z_bases.append(0.0)

    gdf["z_base"] = z_bases
    gdf.to_file(READY_FILE, driver="GPKG")
    print(f"Wrote ready dataset to {READY_FILE}")


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    wfs_data = download_wfs()
    merged = merge_new_features(wfs_data)
    enrich_features(merged)
    prepare_2d_ready()
    print("Pipeline complete.")


if __name__ == "__main__":
    main()
