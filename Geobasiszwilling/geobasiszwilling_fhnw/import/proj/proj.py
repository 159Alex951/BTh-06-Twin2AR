import json
import time
import requests

# 1) CONFIG ---------------------------------------------------------

# WFS URL you used before to get projected buildings
WFS_URL = "https://geodienste.ch/db/av_0/deu" 


# Example WFS params – adapt to your service / layer / bbox
lon_center = float(7.637)
lat_center = float(47.531)

dlat = 0.18
dlon = 0.27

west  = lon_center - dlon
east  = lon_center + dlon
south = lat_center - dlat
north = lat_center + dlat

WFS_PARAMS = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "ms:LCSFPROJ",
        "OUTPUTFORMAT": "application/json; subtype=geojson",
        "SRSNAME": "EPSG:4326",
        "BBOX": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326", # for testing to minimize data size; remove bbox for full data
    }

RAW_GEOJSON = "projected_buildings_raw.geojson"
ENRICHED_GEOJSON = "projected_buildings_enriched.geojson"

BFS_BASE = "https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/"

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


# 2) STEP A: download projected buildings (comment out after first run) ------------------------------

def download_projected_geojson():
    print("Requesting projected buildings from WFS ...")
    r = requests.get(WFS_URL, params=WFS_PARAMS, timeout=60)
    r.raise_for_status()
    data = r.json()
    print("Features from WFS:", len(data.get("features", [])))

    # Keep only features with Art == 'Gebaeude'
    features = data.get("features", [])
    filtered = [
        f for f in features
        if (f.get("properties") or {}).get("Art") == "Gebaeude"
    ]
    data["features"] = filtered
    print("Features after Art='Gebaeude' filter:", len(filtered))

    with open(RAW_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("Saved raw projected buildings to", RAW_GEOJSON)


# 3) STEP B: enrich with gastw from BFS ------------------------------

def fetch_attrs_for_egid(egid: str | int) -> dict:
    """Return selected BFS attributes for an EGID, or {} on error."""
    egid_str = str(egid)
    url = f"{BFS_BASE}{egid_str}_0?f=json&lang=de"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        attrs = (
            data.get("attributes")
            or data.get("properties")
            or (data.get("feature") or {}).get("attributes")
            or {}
        )

        gastw = attrs.get("gastw")
        strname_deinr = attrs.get("strname_deinr")
        ggdename = attrs.get("ggdename")
        lparz = attrs.get("lparz")
        gstat = attrs.get("gstat")
        gkat = attrs.get("gkat")
        garea = attrs.get("garea")
        gvol = attrs.get("gvol")
        gebf = attrs.get("gebf")

        # decode status and category (keep both code and text)
        try:
            gstat_code = int(gstat) if gstat is not None else None
        except ValueError:
            gstat_code = None
        try:
            gkat_code = int(gkat) if gkat is not None else None
        except ValueError:
            gkat_code = None

        result = {
            "gastw": gastw,
            "strname_deinr": strname_deinr,
            "ggdename": ggdename,
            "lparz": lparz,
            "gstat": gstat_code,
            "gstat_text": GSTAT_MAP.get(gstat_code),
            "gkat": gkat_code,
            "gkat_text": GKAT_MAP.get(gkat_code),
            "garea": garea,
            "gvol": gvol,
            "gebf": gebf,
        }

        print(f"EGID {egid_str}: gastw={gastw}, gstat={gstat_code}, gkat={gkat_code}")
        return result

    except Exception as e:
        print(f"EGID {egid_str}: error {e}")
        return {}



def enrich_with_bfs_attrs():
    print("Loading", RAW_GEOJSON)
    with open(RAW_GEOJSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    print("Features to enrich:", len(features))

    # Collect unique EGIDs from projected data
    egids = set()
    for feat in features:
        props = feat.get("properties") or {}
        egid = props.get("GWR_EGID") or props.get("egid")
        if egid not in (None, "", "-"):
            egids.add(str(egid))

    print("Unique EGIDs found:", len(egids))

    # Fetch attribute dict per EGID
    bfs_cache: dict[str, dict] = {}
    egid_list = sorted(egids)
    total = len(egid_list)
    start = time.time()

    for idx, egid in enumerate(egid_list, start=1):
        bfs_cache[egid] = fetch_attrs_for_egid(egid)

        elapsed = time.time() - start
        avg_per_egid = elapsed / idx
        remaining = total - idx
        eta_sec = remaining * avg_per_egid

        print(
            f"[{idx}/{total}] "
            f"elapsed {elapsed:5.1f}s, "
            f"ETA {eta_sec:5.1f}s"
        )

        time.sleep(0.15)  # be friendly to the API

    # Write attributes into each feature
    for feat in features:
        props = feat.get("properties") or {}
        egid = props.get("GWR_EGID") or props.get("egid")
        if egid not in (None, "", "-"):
            extra = bfs_cache.get(str(egid), {})
        else:
            extra = {}

        # merge: gastw, address, Gemeinde, parcel, status, category, areas, volumes
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

        feat["properties"] = props

    data["features"] = features
    with open(ENRICHED_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("Saved enriched projected buildings to", ENRICHED_GEOJSON)

import json

def check_gastw_garea_gvol():
    with open(ENRICHED_GEOJSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    total = len(features)

    gastw_null = 0
    gastw_null_garea_gvol = 0

    gastw_not_null = 0
    gastw_not_null_garea_gvol = 0

    for feat in features:
        props = feat.get("properties") or {}
        gastw = props.get("gastw")
        garea = props.get("garea")
        gvol = props.get("gvol")

        if gastw is None:
            gastw_null += 1
            if garea is not None and gvol is not None:
                gastw_null_garea_gvol += 1
        else:
            gastw_not_null += 1
            if garea is not None and gvol is not None:
                gastw_not_null_garea_gvol += 1

    print("Total features:", total)
    print("gastw is NULL:", gastw_null)
    print("gastw NULL & garea,gvol NOT NULL:", gastw_null_garea_gvol)
    print("gastw is NOT NULL:", gastw_not_null)
    print("gastw NOT NULL & garea,gvol NOT NULL:", gastw_not_null_garea_gvol)
    



# 4) MAIN ------------------------------------------------------------

if __name__ == "__main__":
    # Step A once, then you can comment it out while tweaking enrichment:
    download_projected_geojson()
    enrich_with_bfs_attrs()
    check_gastw_garea_gvol()
