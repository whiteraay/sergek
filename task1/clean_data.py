"""
Data engineering step: clean and enrich parkings_almaty.csv
Run BEFORE uploading to Google Sheets.
"""
import pandas as pd
import re, json, sys
from pathlib import Path

INPUT  = "data/parkings_almaty.csv"
OUTPUT = "data/parkings_almaty_clean.csv"

# ── load ──────────────────────────────────────────────────────────────────────
df = pd.read_csv(INPUT, encoding="utf-8-sig", dtype=str).fillna("")
print(f"Loaded {len(df)} rows, {len(df.columns)} columns")
print("Columns:", list(df.columns))
print("\nMissing values per column:")
print((df == "").sum())

# ── 1. deduplicate ────────────────────────────────────────────────────────────
before = len(df)
df = df.drop_duplicates(subset=["id"], keep="first")
df = df[df["id"].str.strip() != ""]
print(f"\nDeduplicated: {before} → {len(df)} rows")

# ── 2. fix name ───────────────────────────────────────────────────────────────
df["name"] = df["name"].str.strip()
df.loc[df["name"] == "", "name"] = "Парковка (без названия)"

# ── 3. clean coordinates ──────────────────────────────────────────────────────
def safe_float(s):
    try: return float(str(s).strip())
    except: return None

df["lat"] = df["lat"].apply(safe_float)
df["lon"] = df["lon"].apply(safe_float)

# Fix swapped lat/lon (Almaty is lat≈43, lon≈76-77)
mask_swapped = df["lat"].notna() & (df["lat"] < 50) & (df["lon"].notna()) & (df["lon"] > 70)
# valid: lat 43.0–43.5, lon 76.5–77.2
mask_bad_lat = df["lat"].notna() & ((df["lat"] < 42) | (df["lat"] > 44))
mask_bad_lon = df["lon"].notna() & ((df["lon"] < 75) | (df["lon"] > 78))
print(f"Rows with suspicious coords: lat={mask_bad_lat.sum()}, lon={mask_bad_lon.sum()}")

# ── 4. enrich: parking_type from name + address ───────────────────────────────
def infer_type(row):
    if row["parking_type"] not in ("", "частная"):
        return row["parking_type"]  # already set
    n = (row["name"] + " " + row["address"]).lower()
    if any(k in n for k in ("бц","бизнес-центр","бизнес центр","офисный","деловой")):
        return "БЦ"
    if any(k in n for k in ("трк","тц","торгово","молл","mall","plaza","маркет")):
        return "ТЦ/ТРК"
    if any(k in n for k in ("аэропорт","airport")):
        return "аэропорт"
    if any(k in n for k in ("жилой","жк","кондо","residential")):
        return "ЖК"
    if any(k in n for k in ("гостиниц","отель","hotel")):
        return "отель"
    if any(k in n for k in ("больниц","клиник","медицин","hospital")):
        return "медучреждение"
    if any(k in n for k in ("городская","муниципальн","акимат")):
        return "городская"
    if any(k in n for k in ("автостоянка", "стоянка №")):
        return "автостоянка"
    return "частная"

df["parking_type"] = df.apply(infer_type, axis=1)

# ── 5. enrich: paid status from name/hours ────────────────────────────────────
def infer_paid(row):
    if row["paid"] != "":
        return row["paid"]
    n = (row["name"] + " " + row.get("tariff","")).lower()
    if "бесплатн" in n:
        return "бесплатная"
    if any(k in n for k in ("платн","тариф","тенге","₸","час")):
        return "платная"
    # Heuristic: БЦ/ТЦ/отели are almost always paid
    if row["parking_type"] in ("БЦ","ТЦ/ТРК","отель","аэропорт"):
        return "вероятно платная"
    # City/municipal often free
    if row["parking_type"] == "городская":
        return "вероятно бесплатная"
    return ""

df["paid"] = df.apply(infer_paid, axis=1)

# ── 6. enrich: url_2gis ───────────────────────────────────────────────────────
mask_no_url = df["url_2gis"].str.strip() == ""
df.loc[mask_no_url, "url_2gis"] = (
    "https://2gis.kz/almaty/geo/" + df.loc[mask_no_url, "id"].str.split("_").str[0]
)

# ── 7. enrich: hours normalization ───────────────────────────────────────────
def clean_hours(h):
    if not h or h.strip() == "":
        return ""
    h = h.strip()
    if "24/7" in h or "круглосуточно" in h.lower():
        return "24/7"
    return h

df["hours"] = df["hours"].apply(clean_hours)

# ── 8. rating as float ────────────────────────────────────────────────────────
def safe_rating(r):
    try:
        v = float(str(r).strip())
        return f"{v:.1f}" if v > 0 else ""
    except:
        return ""

df["rating"] = df["rating"].apply(safe_rating)

# ── 9. district fill from address ────────────────────────────────────────────
DISTRICT_KEYWORDS = {
    "Алмалинский": ["алмалин","panfilov","панфилова","алма-ата","гоголя","кабанбай"],
    "Бостандыкский": ["бостандык","аль-фараби","достык","горная","розыбакиева"],
    "Медеуский": ["медеу","самал","юбилейный","кокжайлау"],
    "Ауэзовский": ["ауэзов","мамыр","шанырак","тастак","жетысу"],
    "Турксибский": ["турксиб","компланировка","карасу"],
    "Жетысуский": ["жетысу","шаган","кулагер"],
    "Наурызбайский": ["наурызбай","акжар","нурлытау","калкаман"],
    "Алатауский": ["алатау","акбулак","акшамшык","заречный"],
}

def infer_district(row):
    if row["district"].strip():
        return row["district"]
    text = (row["address"] + " " + row["name"]).lower()
    for dist, kws in DISTRICT_KEYWORDS.items():
        if any(k in text for k in kws):
            return dist
    return ""

df["district"] = df.apply(infer_district, axis=1)

# ── 10. add google maps link ──────────────────────────────────────────────────
def gmaps(row):
    if pd.notna(row["lat"]) and pd.notna(row["lon"]) and row["lat"] and row["lon"]:
        return f"https://maps.google.com/?q={row['lat']},{row['lon']}"
    return ""

df["google_maps_url"] = df.apply(gmaps, axis=1)

# ── 11. remove garbage rows ───────────────────────────────────────────────────
# Drop rows with no name AND no address AND no coords
mask_empty = (
    (df["name"] == "Парковка (без названия)") &
    (df["address"] == "") &
    (df["lat"].isna())
)
print(f"Dropping {mask_empty.sum()} completely empty rows")
df = df[~mask_empty]

# ── 12. sort ──────────────────────────────────────────────────────────────────
df = df.sort_values(["district","parking_type","name"], na_position="last")

# ── final stats ───────────────────────────────────────────────────────────────
print(f"\n=== FINAL DATASET: {len(df)} rows ===")
print("\nparking_type distribution:")
print(df["parking_type"].value_counts())
print("\npaid distribution:")
print(df["paid"].value_counts())
print(f"\nRows with coordinates: {df['lat'].notna().sum()}")
print(f"Rows with hours:       {(df['hours'] != '').sum()}")
print(f"Rows with rating:      {(df['rating'] != '').sum()}")

# ── save ──────────────────────────────────────────────────────────────────────
FINAL_COLS = [
    "id","name","address","city","district",
    "lat","lon","url_2gis","google_maps_url",
    "parking_type","paid","tariff","capacity",
    "parent_object","hours","rating","review_count","has_photos"
]
# Only keep columns that exist
final_cols = [c for c in FINAL_COLS if c in df.columns]
df[final_cols].to_csv(OUTPUT, index=False, encoding="utf-8-sig")
print(f"\n✅ Saved clean data → {OUTPUT}")
