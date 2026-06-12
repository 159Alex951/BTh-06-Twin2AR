import os
import rasterio
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine
from pathlib import Path

# Paths
DB_USER = "postgres"
DB_PASS = "admin"
DB_HOST = "localhost"   # Make sure port 5432 is exposed out of the Docker container as before
DB_PORT = "5432"
DB_NAME = "postgres"

# Resolve directories relative to the script location
BASE_DIR = Path(__file__).resolve().parent.parent
TERRAIN_DIR = BASE_DIR / "import" / "terrain"

# Choose the source of your newest projected buildings:
# Using the filtered GeoJSON with only ~2500 footprints around the AOI
SOURCE_FILE = BASE_DIR / "import" / "proj" / "projected_buildings_enriched.geojson"

def build_hybrid_elevation_logic():
    print("Loading TIFF bounds...")
    tiff_files = list(TERRAIN_DIR.glob("*.tif"))
    
    # Extract bounding boxes once so we don't open 714 files for every single corner point
    tiff_bounds = []
    print(f"Pre-scanning bounds of {len(tiff_files)} TIFFs...")
    for tiff in tiff_files:
        try:
            with rasterio.open(tiff) as src:
                bounds = src.bounds
                tiff_bounds.append({
                    "path": tiff,
                    "left": bounds.left,
                    "right": bounds.right,
                    "bottom": bounds.bottom,
                    "top": bounds.top
                })
        except:
            continue
    print(f"Cached bounds for {len(tiff_bounds)} TIFFs.")
    return tiff_bounds
    
def get_elevation_hybrid(x, y, tiff_bounds):
    """Hybrid logical query with pre-cached bounds."""
    for tb in tiff_bounds:
        if tb["left"] <= x <= tb["right"] and tb["bottom"] <= y <= tb["top"]:
            # We found the correct TIFF bounds! Now open and sample
            try:
                with rasterio.open(tb["path"]) as src:
                    for val in src.sample([(x, y)]):
                        z_val = val[0]
                        if z_val != src.nodata and z_val > -500:
                            return float(z_val)
            except:
                continue
            
    # Could add API fallback here as shown earlier, simply return 0 if nowhere
    return 0.0

def process_waterfall_height(row):
    """
    1. Check if we have volume vs area
    2. Check floors
    3. Check gkat
    4. Fallback
    """
    gvol = float(row.get('gvol', 0) or 0)
    garea = float(row.get('garea', 0) or 0)
    gastw = float(row.get('gastw', 0) or 0)
    gkat_raw = row.get('gkat', '')
    
    # Safely handle float values like '1080.0' or '1060.0'
    try:
        gkat = str(int(float(gkat_raw)))
    except (ValueError, TypeError):
        gkat = str(gkat_raw).strip()

    floor_mult = 3.0 if gkat == '1060' else 2.5
    raw_stw = (gastw * floor_mult) if gastw > 0 else None
    raw_vol = (gvol / garea) if (gvol > 0 and garea > 0) else None

    final_h = None
    source = None

    if raw_vol is not None:
        use_vol = True
        if raw_vol < 2.0:
            use_vol = False
            
        if use_vol and raw_stw is not None:
            diff_pct = abs(raw_vol - raw_stw) / raw_stw
            if gkat == '1060':
                if diff_pct > 2.0:  # 200% off
                    use_vol = False
            elif gkat in ['1020', '1030', '1040']:
                if diff_pct > 1.0:  # 100% off
                    use_vol = False
            else:
                if diff_pct > 1.0:
                    use_vol = False
                    
        if use_vol:
            final_h = raw_vol
            source = 'volume_math'

    if final_h is None and raw_stw is not None:
        final_h = raw_stw
        source = 'floors_math'

    if final_h is None:
        if gkat == '1060':
            final_h = 9.0
            source = 'category_fallback_1060'
        elif gkat == '1080':
            final_h = 0.0
            source = 'ignore' 
        else:
            final_h = 7.5
            source = 'absolute_fallback'

    # If it was calculated but it's a 1080, force it to 0.0 and ignore
    if gkat == '1080':
        final_h = 0.0
        source = 'ignore'

    return final_h, source, raw_vol, raw_stw

def main():
    print(f"Loading {SOURCE_FILE.name} into GeoPandas...")
    gdf = gpd.read_file(SOURCE_FILE)
    
    # Needs to be LV95 for DTM lookup
    if gdf.crs.to_epsg() != 2056:
        print("Converting coordinates to LV95 (EPSG:2056)...")
        gdf = gdf.to_crs(epsg=2056)
    
    # 1. Execute Height Waterfall
    print("Applying height waterfall logic...")
    heights = []
    sources = []
    raw_vols = []
    raw_stws = []
    for idx, row in gdf.iterrows():
        h, source, raw_v, raw_s = process_waterfall_height(row)
        heights.append(h)
        sources.append(source)
        raw_vols.append(raw_v)
        raw_stws.append(raw_s)
    
    gdf['computed_height'] = heights
    gdf['height_source'] = sources
    gdf['height_raw_gvol'] = raw_vols
    gdf['height_raw_gastw'] = raw_stws
    
    start_len = len(gdf)
    gdf = gdf[gdf['height_source'] != 'ignore'].copy()
    print(f"Filtered out {start_len - len(gdf)} buildings marked as ignore (gkat=1080).")

    # 2. Extract Base Elevation (Z_base)
    print("Calculating DTM base elevations...")
    tiffs = build_hybrid_elevation_logic()
    
    z_bases = []
    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            z_bases.append(0.0)
            continue
            
        # Get coordinates of exterior ring to sample terrain
        try:
            # MultiPolygons vs Polygons handling
            if geom.geom_type == 'Polygon':
                coords = list(geom.exterior.coords)
            elif geom.geom_type == 'MultiPolygon':
                # Just take the first polygon for simplicity of the base block
                coords = list(geom.geoms[0].exterior.coords)
            else:
                coords = []
                
            if not coords:
                z_bases.append(0.0)
                continue
                
            # Sample all corners
            corner_z = []
            for x, y in coords:
                elev = get_elevation_hybrid(x, y, tiffs)
                if elev > 0:
                    corner_z.append(elev)
                    
            if corner_z:
                z_bases.append(min(corner_z))
            else:
                z_bases.append(0.0)
                
        except Exception as e:
            z_bases.append(0.0)
            
    gdf['z_base'] = z_bases

    # Drop columns with complex objects if they exist
    if 'geometry' in gdf:
        # we keep geometry as active geometry column
        pass

    out_file = BASE_DIR / "import" / "proj" / "projected_buildings_2d_ready.gpkg"
    print(f"Writing to {out_file}...")
    gdf.to_file(out_file, driver="GPKG")
    
    print("Done! Data is ready to be loaded via ogr2ogr into the database.")

if __name__ == "__main__":
    main()