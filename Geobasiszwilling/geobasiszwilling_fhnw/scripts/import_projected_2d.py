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
    return tiff_files
    
def get_elevation_hybrid(x, y, tiffs):
    """Placeholder hybrid logical query."""
    for tiff_path in tiffs:
        try:
            with rasterio.open(tiff_path) as src:
                if (src.bounds.left <= x <= src.bounds.right and 
                    src.bounds.bottom <= y <= src.bounds.top):
                    # We found a matching TIFF! Check pixel
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
    gkat = str(row.get('gkat', ''))

    if gvol > 0 and garea > 0:
        return (gvol / garea), 'volume_math'
    elif gastw > 0:
        return (gastw * 3.0), 'floors_math'
    elif gkat == '1020': # Assume 1020 is residential 
        return 6.0, 'category_residential'
    elif gkat == '1030': # Assume 1030 is industrial
        return 8.0, 'category_industrial'
    elif gkat == '1040': # Assume 1040 is agricultural
        return 5.0, 'category_agricultural'
    else:
        return 6.0, 'absolute_fallback'

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
    for idx, row in gdf.iterrows():
        h, source = process_waterfall_height(row)
        heights.append(h)
        sources.append(source)
    
    gdf['computed_height'] = heights
    gdf['height_source'] = sources

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

    # Drop columns that Postgres won't like, keep strings and floats
    print("Connecting to PostgreSQL and writing to table projected_buildings_2d...")
    engine = create_engine(f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}')
    
    # Send directly via GeoPandas to PostGIS!
    gdf.to_postgis("projected_buildings_2d", engine, schema="citydb", if_exists="replace")
    print("Done! Check 'citydb.projected_buildings_2d' using pgAdmin/DBeaver.")

if __name__ == "__main__":
    main()