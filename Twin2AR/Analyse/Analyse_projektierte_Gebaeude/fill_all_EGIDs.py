import requests
import geopandas as gpd
import pandas as pd
from tqdm import tqdm
import time
import random
import os

# ── 1. LOAD GEOJSON ───────────────────────────────────────────────────────────
gdf = gpd.read_file("buildings.geojson")
print(f"Loaded {len(gdf)} features | CRS: {gdf.crs}")

# Make sure egid is numeric
gdf["egid"] = pd.to_numeric(gdf["egid"], errors="coerce")

# Only rows with a valid EGID
has_egid = gdf["egid"].notna() & (gdf["egid"] != 0)
print(f"EGID coverage: {has_egid.sum()} / {len(gdf)} ({has_egid.mean()*100:.1f}%)")

egid_gdf = gdf[has_egid].copy()
TEST_MODE = False          # ← set to False for full run
unique_egids = egid_gdf["egid"].dropna().unique().astype("int64")
egids = unique_egids[:500] if TEST_MODE else unique_egids  # use 500 for a more realistic test
print(f"\nRunning in {'TEST' if TEST_MODE else 'FULL'} mode — {len(egids):,} EGIDs")

# ── 2. API CALL FUNCTION ──────────────────────────────────────────────────────
GWR_URL = "https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/{egid}_0"

def fetch_gwr(egid):
    try:
        r = requests.get(GWR_URL.format(egid=int(egid)), timeout=10)
        if r.status_code == 200:
            data = r.json()
            attrs = data.get("feature", {}).get("attributes", {})
            subset = {
                "egid":  int(egid),
                "garea": attrs.get("garea"),
                "gvol":  attrs.get("gvol"),
                "gastw": attrs.get("gastw"),
            }
            return subset
    except Exception as e:
        print(f"Error for EGID {egid}: {e}")
    return None

# ── 3. LOOP OVER EGIDs WITH CHECKPOINTS ───────────────────────────────────────
CHUNK_SIZE = 50_000
SLEEP_BASE = 0.01   # ~9 req/s  
SLEEP_JITTER = 0.005

results = []
chunk_idx = 0
total_fetched = 0

os.makedirs("gwr_chunks", exist_ok=True)

for i, eid in enumerate(tqdm(egids, desc="Fetching GWR")):
    row = fetch_gwr(eid)
    if row:
        results.append(row)
        total_fetched += 1

    # ~9 req/s with small random jitter
    time.sleep(SLEEP_BASE + random.uniform(0, SLEEP_JITTER))

    # Save a chunk every CHUNK_SIZE successful fetches (not loop iterations)
    if total_fetched > 0 and total_fetched % CHUNK_SIZE == 0:
        chunk_idx += 1
        chunk_df = pd.DataFrame(results)
        chunk_file = f"gwr_chunks/gwr_chunk_{chunk_idx:04d}.parquet"
        chunk_df.to_parquet(chunk_file, index=False)
        print(f"\n[Checkpoint] Saved chunk {chunk_idx} with {len(chunk_df):,} records → {chunk_file}")
        results = []  # clear in-memory list

# Save remaining results after loop
if results:
    chunk_idx += 1
    chunk_df = pd.DataFrame(results)
    chunk_file = f"gwr_chunks/gwr_chunk_{chunk_idx:04d}.parquet"
    chunk_df.to_parquet(chunk_file, index=False)
    print(f"\n[Checkpoint] Saved final chunk {chunk_idx} with {len(chunk_df):,} records → {chunk_file}")

print(f"\nTotal fetched records: {total_fetched:,}")

# ── 4. COMBINE CHUNKS ─────────────────────────────────────────────────────────
print("\nCombining chunks...")
chunk_files = sorted([f for f in os.listdir("gwr_chunks") if f.endswith(".parquet")])

all_chunks = []
for f_name in chunk_files:
    path = os.path.join("gwr_chunks", f_name)
    df_chunk = pd.read_parquet(path)
    all_chunks.append(df_chunk)
    print(f"Loaded {f_name} with {len(df_chunk):,} rows")

if all_chunks:
    gwr_df = pd.concat(all_chunks, ignore_index=True)
else:
    gwr_df = pd.DataFrame(columns=["egid", "garea", "gvol", "gastw"])

print(f"\nCombined GWR records: {len(gwr_df):,}")
print(gwr_df.head())

# ── 5. MERGE BACK INTO GEOJSON GDF ────────────────────────────────────────────
gwr_df["egid"] = pd.to_numeric(gwr_df["egid"], errors="coerce")

gdf_enriched = gdf.merge(gwr_df, on="egid", how="left")
print(f"\nEnriched shape: {gdf_enriched.shape}")
print(gdf_enriched[["egid", "garea", "gvol", "gastw"]].head())

# ── 6. SAVE ───────────────────────────────────────────────────────────────────
out_file = "whatamidoing_test.geojson" if TEST_MODE else "whatamidoing.geojson"
gdf_enriched.to_file(out_file, driver="GeoJSON")
print(f"\nSaved final enriched GeoJSON → {out_file}")