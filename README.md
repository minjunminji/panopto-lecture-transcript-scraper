# Panopto Transcript Scraper

Download caption transcripts for every recording inside a Panopto course folder.  
Point the script at any Panopto folder/list URL and it will save each transcript as a `.txt` file while keeping track of what has already been downloaded.

## Features
- Works with any Panopto instance that exposes the standard course folder UI.
- Saves one text file per recording using a sanitized filename based on the lecture title.
- Keeps a lightweight state file so repeat runs only fetch new recordings.
- Headless Chrome by default, but can open a visible browser window for first-time SSO logins.

## Prerequisites
- Python 3.9 or newer.
- Google Chrome installed on the host machine.
- Access to the Panopto folder you want to scrape (usually requires being logged in via your institution's SSO).

## Quick Start
1. Create and activate a virtual environment (recommended).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Authenticate with Panopto in a normal browser first so the session cookies are available to Chrome.
4. Run the scraper with your course folder URL:
   ```bash
   python scraper.py --folder-url "https://your.panopto.host/Panopto/Pages/Sessions/List.aspx#folderID=%22..." 
   ```

Transcripts will be written to `transcripts/` and the scraper history will live in `data/scraped_sessions.txt`. Both locations can be customized via CLI flags.

## CLI Options
```text
python scraper.py --folder-url URL [--output-dir DIR] [--state-file PATH]
                  [--no-headless] [--timeout SECONDS] [--reset-state]
```

- `--folder-url` *(required)*: Link to the Panopto course folder (be sure you are on the list view page).
- `--output-dir`: Directory for transcript files. Defaults to `transcripts/`.
- `--state-file`: File used to track already-downloaded lectures. Defaults to `data/scraped_sessions.txt`. Set to an empty string to disable state tracking entirely.
- `--no-headless`: Launch Chrome with a visible window. Helpful the first time you need to complete SSO or MFA.
- `--timeout`: Seconds to wait for page elements to appear. Increase this if Panopto loads slowly on your network.
- `--reset-state`: Delete the state file before scraping so every lecture is downloaded again.

## Tips
- If you run into authentication loops, try `--no-headless` once, complete the login flow in the real browser window, then close it and rerun in headless mode.
- Panopto occasionally changes CSS selectors. If the script suddenly stops finding videos or transcripts, search for the selectors defined near the top of `scraper.py` and update them to match the new markup.
- Be mindful of your institution's policies when downloading and redistributing lecture content.

## License
Released under the MIT License. See [LICENSE](LICENSE) for details.
