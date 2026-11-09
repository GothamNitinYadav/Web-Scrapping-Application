"""Optional runtime dependencies and browser/display settings."""

import os
import sys

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    SELENIUM_AVAILABLE = True
except ImportError:
    webdriver = None
    By = None
    ActionChains = None
    Options = None
    WebDriverWait = None
    SELENIUM_AVAILABLE = False

    class Keys:
        COMMAND = "COMMAND"
        CONTROL = "CONTROL"
        ESCAPE = "ESCAPE"
        BACKSPACE = "BACKSPACE"
        ENTER = "ENTER"

        @staticmethod
        def chord(*values):
            return " ".join(str(value) for value in values)

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    BS4_AVAILABLE = False

SIDE_BY_SIDE = os.environ.get("WEB_SCRAPER_SIDE_BY_SIDE", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
MIN_BROWSER_WIDTH = int(os.environ.get("WEB_SCRAPER_MIN_BROWSER_WIDTH", "950"))
SCREEN_W = 1920
SCREEN_H = 1080
GUI_WIDTH = 840
SELECT_ALL_KEY = Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL
