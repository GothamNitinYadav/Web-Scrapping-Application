# Dynamic Web Scraping Studio

## Run

Install the Python dependencies and launch the desktop application:

```powershell
python -m pip install -r requirements.txt
python "web_scraper\main.py"
```

You can also run the backwards-compatible launcher, `web scrapping application.py`.

Google Chrome is required for scraping. The interface can still open if the
scraping dependencies are not installed.

## Project layout

- `web scrapping application.py` is the backwards-compatible launcher.
- `web_scraper/main.py` launches the application from the package folder.
- `web_scraper/gui.py` contains the Tkinter interface and scraping workflow.
- `web_scraper/scraper.py` contains browser automation and product extraction.
- `web_scraper/config.py` contains selectors and parsing patterns.
- `web_scraper/themes.py` contains the UI color palette.
- `web_scraper/environment.py` handles optional dependencies and runtime
  settings.

Set `WEB_SCRAPER_SIDE_BY_SIDE=true` to place Chrome beside the interface when
there is enough display width. `WEB_SCRAPER_MIN_BROWSER_WIDTH` sets the
minimum width for the browser window in that layout (default: `950`).
