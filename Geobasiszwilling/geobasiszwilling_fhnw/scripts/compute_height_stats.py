import sys
import json
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_FILE = BASE_DIR / "import" / "proj" / "projected_buildings_enriched_ch.geojson"

def process_waterfall_height(props):
    gvol = float(props.get('gvol', 0) or 0)
    garea = float(props.get('garea', 0) or 0)
    gastw = float(props.get('gastw', 0) or 0)
    gkat_raw = props.get('gkat', '')
    
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
            final_h = 10.0
            source = 'category_fallback_1060'
        elif gkat == '1080':
            final_h = 0.0
            source = 'ignore' 
        else:
            final_h = 6.0
            source = 'absolute_fallback'

    if gkat == '1080':
        final_h = 0.0
        source = 'ignore'

    return final_h, source, raw_vol, raw_stw

def main():
    if not SOURCE_FILE.exists():
        print(f"File not found: {SOURCE_FILE}")
        sys.exit(1)

    print(f"Loading data from {SOURCE_FILE.name}...")
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = []
    
    features = data.get("features", [])
    print(f"Processing {len(features)} buildings...")
    
    for f in features:
        props = f.get("properties", {})
        egid = props.get("egid") or props.get("EGID")
        
        computed_height, height_source, height_raw_gvol, height_raw_gastw = process_waterfall_height(props)
        
        results.append({
            "egid": egid,
            "gkat": props.get("gkat"),
            "height_raw_gvol": height_raw_gvol,
            "height_raw_gastw": height_raw_gastw,
            "computed_height": computed_height,
            "height_source": height_source
        })

    df = pd.DataFrame(results)
    
    print("\n" + "="*50)
    print("HEIGHT STATISTICS")
    print("="*50)
    
    # 1. Provide an overview of the sources
    print("\n--- Distribution of Height Sources ---")
    print(df['height_source'].value_counts())
    
    print("\n--- Overview of Computed Heights (Meters) ---")
    valid_heights = df[df['height_source'] != 'ignore']['computed_height']
    print(valid_heights.describe())
    
    # Save purely the stats data to a CSV
    out_csv = BASE_DIR / "import" / "proj" / "height_statistics_enriched_ch.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nSaved raw detailed data of sizes/sources to {out_csv}")

if __name__ == "__main__":
    main()