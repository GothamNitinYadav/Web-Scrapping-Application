"""Launch the Dynamic Web Scraping Studio from inside the package."""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web_scraper.gui import main


if __name__ == "__main__":
    main()
