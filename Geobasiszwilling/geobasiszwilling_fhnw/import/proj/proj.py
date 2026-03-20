import json
import time
import requests

# 1) CONFIG ---------------------------------------------------------

# WFS URL you used before to get projected buildings (replace with your real one)
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
        "BBOX": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326",
        "COUNT": 5000,
    }

RAW_GEOJSON = "projected_buildings_raw.geojson"
ENRICHED_GEOJSON = "projected_buildings_enriched.geojson"

BFS_BASE = "https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/"


# 2) STEP A: download projected buildings (comment out after first run) ------------------------------

def download_projected_geojson():
    print("Requesting projected buildings from WFS ...")
    r = requests.get(WFS_URL, params=WFS_PARAMS, timeout=60)
    r.raise_for_status()
    data = r.json()
    print("Features from WFS:", len(data.get("features", [])))

    with open(RAW_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("Saved raw projected buildings to", RAW_GEOJSON)


# 3) STEP B: enrich with gastw from BFS ------------------------------

def fetch_gastw_for_egid(egid: str | int) -> int | None:
    """Return gastw (number of floors) for given EGID, or None."""
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
        val = attrs.get("gastw")
        print(f"EGID {egid_str}: gastw = {val}")
        return val
    except Exception as e:
        print(f"EGID {egid_str}: error {e}")
        return None


def enrich_with_gastw():
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

    # Fetch gastw per EGID
    gastw_cache: dict[str, int | None] = {}
    egid_list = sorted(egids)
    total = len(egid_list)
    start = time.time()

    for idx, egid in enumerate(egid_list, start=1):
        gastw_cache[egid] = fetch_gastw_for_egid(egid)

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


    # Write gastw into each feature
    for feat in features:
        props = feat.get("properties") or {}
        egid = props.get("GWR_EGID") or props.get("egid")
        if egid not in (None, "", "-"):
            g = gastw_cache.get(str(egid))
        else:
            g = None
        props["gastw"] = g
        feat["properties"] = props

    # Save enriched file
    data["features"] = features
    with open(ENRICHED_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("Saved enriched projected buildings to", ENRICHED_GEOJSON)


# 4) MAIN ------------------------------------------------------------

if __name__ == "__main__":
    # Step A once, then you can comment it out while tweaking enrichment:
    # download_projected_geojson()
    enrich_with_gastw()
