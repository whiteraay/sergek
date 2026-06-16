"""
Upload cleaned CSV to Google Sheets.
Run after clean_data.py.

Setup (one-time):
  1. Google Cloud Console → enable Sheets API + Drive API
  2. IAM → Service Accounts → Create → download JSON as service_account.json
  3. Share your Google Sheet with the service account email (Editor)
  4. python upload_to_sheets.py --sheets-id YOUR_ID
"""
import csv, time, logging, sys, os, argparse
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

def upload(csv_path: str, spreadsheet_id: str):
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        log.error("Run: pip install gspread google-auth")
        sys.exit(1)

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", service_account_path := serviceacc)
    if not os.path.exists(creds_path):
        log.error(
            f"'{creds_path}' not found.\n"
            "  1. Go to console.cloud.google.com\n"
            "  2. Create service account → download JSON key\n"
            "  3. Save as service_account.json in this folder\n"
            "  4. Share your Google Sheet with the service account email"
        )
        sys.exit(1)

    scopes = ["https://www.googleapis.com/auth/spreadsheets",
              "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)

    # Load CSV
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        log.error("CSV is empty")
        sys.exit(1)

    log.info(f"Uploading {len(rows)-1} rows to Sheets...")
    ws = gc.open_by_key(spreadsheet_id).sheet1
    ws.clear()

    # Upload in chunks (Sheets API limit: 500 rows per call)
    CHUNK = 500
    ws.update([rows[0]] + rows[1:min(CHUNK+1, len(rows))])
    for i in range(CHUNK+1, len(rows), CHUNK):
        ws.append_rows(rows[i:i+CHUNK])
        time.sleep(1.2)  # respect quota

    log.info(f"✅ Done! https://docs.google.com/spreadsheets/d/{spreadsheet_id}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",       default="data/parkings_almaty_clean.csv")
    parser.add_argument("--sheets-id", required=True)
    args = parser.parse_args()
    upload(args.csv, args.sheets_id)
