import requests

# Put 10 real EGIDs here (for testing you can copy from your projected-building properties)
EGIDS = [
    243058419,
    # ...9 more EGIDs...
]

BASE_URL = "https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/"

def fetch_attrs_for_egid(egid: int):
    url = f"{BASE_URL}{egid}_0?f=json&lang=de"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    attrs = (
        data.get("attributes")
        or data.get("properties")
        or (data.get("feature") or {}).get("attributes")
        or {}
    )
    return attrs

def main():
    for egid in EGIDS:
        print("=" * 60)
        print(f"EGID {egid}")
        try:
            attrs = fetch_attrs_for_egid(egid)
        except Exception as e:
            print("  ERROR:", e)
            continue

        # Print all keys and a shortened value
        for key, value in attrs.items():
            text = str(value)
            if len(text) > 80:
                text = text[:77] + "..."
            print(f"  {key:25s} = {text}")

if __name__ == "__main__":
    main()
