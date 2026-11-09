"""Browser automation and product extraction logic."""

import json
import re
import time
from urllib.parse import (
    parse_qs, quote_plus, urlencode, urljoin, urlparse, urlunparse
)

from . import environment
from .config import (
    BAD_TITLES, GENERIC_CARD_SELECTORS, KNOWN_SEARCH_URLS, PRICE_PATTERN,
    PRODUCT_LINK_SELECTOR, PRODUCT_URL_RE, RATING_PATTERN, SITE_CONFIG, SKIP_LINES,
)
from .environment import (
    ActionChains, BS4_AVAILABLE, BeautifulSoup, By, Keys, Options,
    SELECT_ALL_KEY, SELENIUM_AVAILABLE, WebDriverWait, webdriver,
)

driver = None
stop_requested = False


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def normalize_url(url):
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def is_valid_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_bad_title(title):
    t = clean_text(title).lower()
    if not t:
        return True
    if t in BAD_TITLES:
        return True
    if re.fullmatch(r"[\d.,%\s()★₹$€£-]+", t):
        return True
    return False


def extract_price(text):
    if not text:
        return ""
    match = PRICE_PATTERN.search(text)
    return clean_text(match.group(0)) if match else ""


def extract_rating(text):
    if not text:
        return "Not available"
    match = RATING_PATTERN.search(text)
    return match.group(1) if match else "Not available"


def get_absolute_url(base_url, link):
    if not link:
        return ""
    return urljoin(base_url, link)


def link_key(href):
    parsed = urlparse(href)
    pid = parse_qs(parsed.query).get("pid", [""])[0]
    return pid or parsed.path


def parse_numeric_price(price_str):
    """Convert price string like '₹45,999' or '$120.50' into a float for sorting."""
    if not price_str or price_str == "Not available":
        return -1.0
    cleaned = re.sub(r"[^\d.]", "", price_str)
    try:
        return float(cleaned)
    except Exception:
        return -1.0


def parse_budget_constraint(query):
    """
    Read a maximum-price condition from a query such as:
      'laptop under 50000', 'phone below ₹25,000',
      'headphones less than 3000', or 'watch upto 5000'.

    Returns (search_terms_without_budget, maximum_price_or_None).
    """
    text = clean_text(query)
    patterns = [
        r"\b(?:under|below|less\s+than|upto|up\s+to|max(?:imum)?|not\s+more\s+than)\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",
        r"\b(?:price\s*)?(?:<=|<)\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)",
    ]
    maximum = None
    cleaned = text
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            try:
                maximum = float(match.group(1).replace(",", ""))
            except ValueError:
                maximum = None
            cleaned = (cleaned[:match.start()] + " " + cleaned[match.end():]).strip()
            break
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,-|")
    return cleaned, maximum


def parse_numeric_rating(rating_str):
    """Convert rating string like '4.3' into a float for sorting."""
    if not rating_str or rating_str == "Not available":
        return -1.0
    try:
        match = re.search(r"\d+(\.\d+)?", rating_str)
        return float(match.group(0)) if match else -1.0
    except Exception:
        return -1.0


def start_driver():
    global driver

    if not SELENIUM_AVAILABLE or not BS4_AVAILABLE:
        missing = []
        if not SELENIUM_AVAILABLE:
            missing.append("selenium")
        if not BS4_AVAILABLE:
            missing.append("beautifulsoup4")
        raise RuntimeError(
            "Missing required package(s): " + ", ".join(missing) +
            ". Open PowerShell and run: python -m pip install -r requirements.txt"
        )

    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass

    options = Options()
    options.add_argument("--disable-features=CalculateNativeWinOcclusion")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--lang=en-IN")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])

    driver = webdriver.Chrome(options=options)
    place_browser_window()
    return driver


def place_browser_window():
    try:
        browser_width = environment.SCREEN_W - environment.GUI_WIDTH
        if environment.SIDE_BY_SIDE and browser_width >= environment.MIN_BROWSER_WIDTH:
            driver.set_window_position(environment.GUI_WIDTH, 0)
            driver.set_window_size(browser_width, environment.SCREEN_H - 40)
        else:
            driver.maximize_window()
    except Exception:
        pass


def wait_for_page_ready(timeout=20):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        pass


def count_product_links():
    try:
        count = len(driver.find_elements(By.CSS_SELECTOR, PRODUCT_LINK_SELECTOR))
        # Also count common retail product-card containers for sites whose URLs do not
        # use the generic /p/ or /product/ patterns (notably Myntra).
        for selector in (".product-base", "li.product-base", "[data-component-type='s-search-result']",
                         ".product-tuple-listing", "li.s-item", ".rilrtl-products-list__item"):
            try:
                count = max(count, len(driver.find_elements(By.CSS_SELECTOR, selector)))
            except Exception:
                pass
        return count
    except Exception:
        return 0


def wait_for_product_links(minimum=3, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if stop_requested:
            return False
        if count_product_links() >= minimum:
            return True
        time.sleep(0.35)
    return False


def dismiss_popups():
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass

    xpaths = [
        "//button[normalize-space(.)='✕']",
        "//span[normalize-space(.)='✕']",
        "//button[@aria-label='Close']",
        "//button[@aria-label='close']",
        "//button[contains(@class,'close')]",
    ]

    for xpath in xpaths:
        try:
            for element in driver.find_elements(By.XPATH, xpath):
                if element.is_displayed():
                    driver.execute_script("arguments[0].click();", element)
                    time.sleep(0.3)
        except Exception:
            continue


def find_search_box():
    selectors = [
        "input[name='q']",
        "input[type='search']",
        "input[name='query']",
        "input[name='search']",
        "input[name='keyword']",
        "input[name='keywords']",
        "input[name='field-keywords']",
        "input[id='search']",
        "input[id='searchbox']",
        "input[id='twotabsearchtextbox']",
        "input[placeholder*='Search']",
        "input[placeholder*='search']",
        "input[aria-label*='Search']",
        "input[aria-label*='search']",
        "input[class*='search']",
        "input[class*='Search']",
    ]

    for selector in selectors:
        try:
            for element in driver.find_elements(By.CSS_SELECTOR, selector):
                try:
                    if element.is_displayed() and element.is_enabled():
                        return element
                except Exception:
                    continue
        except Exception:
            continue
    return None


def search_using_box(query):
    dismiss_popups()
    box = find_search_box()
    if box is None:
        return False

    old_url = driver.current_url

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
        time.sleep(0.4)
        try:
            box.click()
        except Exception:
            dismiss_popups()
            driver.execute_script("arguments[0].focus(); arguments[0].click();", box)

        box.send_keys(Keys.chord(SELECT_ALL_KEY, "a"))
        box.send_keys(Keys.BACKSPACE)
        box.send_keys(query)
        time.sleep(0.6)
        box.send_keys(Keys.ENTER)
    except Exception as e:
        print("Search box error:", e)
        return False

    end = time.time() + 12
    while time.time() < end:
        if driver.current_url != old_url:
            wait_for_page_ready()
            return True
        time.sleep(0.5)

    return False


def create_search_urls(base_url, query):
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    q = quote_plus(query)

    urls = [
        f"{origin}/search?q={q}",
        f"{origin}/search?query={q}",
        f"{origin}/search?keyword={q}",
        f"{origin}/search?search={q}",
        f"{origin}/search?type=product&q={q}",
        f"{origin}/s?k={q}",
        f"{origin}/catalogsearch/result/?q={q}",
        f"{origin}/?s={q}&post_type=product",
        f"{origin}/?q={q}",
    ]

    existing = parse_qs(parsed.query)
    for parameter in ("q", "query", "search", "keyword", "keywords"):
        params = existing.copy()
        params[parameter] = [query]
        new_url = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, urlencode(params, doseq=True), parsed.fragment
        ))
        if new_url not in urls:
            urls.append(new_url)

    return urls


def get_known_search_url(url, query):
    """Build a known search-results URL for supported stores."""
    host = urlparse(url).netloc.lower()
    if host.endswith("myntra.com"):
        slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
        return f"https://www.myntra.com/{slug}"
    for domain, template in KNOWN_SEARCH_URLS.items():
        if host == domain or host.endswith("." + domain):
            return template.format(q=quote_plus(query))
    if host.endswith("ajio.com"):
        return f"https://www.ajio.com/search/?text={quote_plus(query)}"
    if host.endswith("meesho.com"):
        return f"https://www.meesho.com/search?q={quote_plus(query)}"
    if host.endswith("nykaa.com"):
        return f"https://www.nykaa.com/search/result/?q={quote_plus(query)}"
    return ""


def page_mentions_query(query):
    words = [
        w for w in re.findall(r"\w+", query.lower())
        if len(w) >= 3 and not w.isdigit()
    ]
    if not words:
        return True
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
    except Exception:
        return False
    return any(w in body for w in words)


def open_and_check(search_url, query, strict):
    try:
        print("Trying search candidate:", search_url)
        driver.get(search_url)
        wait_for_page_ready()
        dismiss_popups()

        if not wait_for_product_links(timeout=12):
            return False

        if strict and not page_mentions_query(query):
            return False

        return True
    except Exception as e:
        print("Open error:", e)
        return False


def perform_search(url, query):
    driver.get(url)
    wait_for_page_ready()
    time.sleep(2)
    dismiss_popups()

    if not query.strip():
        return driver.current_url

    known_url = get_known_search_url(url, query)
    if known_url:
        if open_and_check(known_url, query, strict=False):
            return driver.current_url
        driver.get(url)
        wait_for_page_ready()
        dismiss_popups()

    if search_using_box(query):
        wait_for_product_links(timeout=12)
        return driver.current_url

    for candidate in create_search_urls(url, query):
        if open_and_check(candidate, query, strict=True):
            return driver.current_url

    return driver.current_url


def scroll_page(steps=8):
    try:
        height = driver.execute_script("return window.innerHeight") or 800
        for _ in range(steps):
            if stop_requested:
                return
            driver.execute_script("window.scrollBy(0, arguments[0]);", int(height * 0.9))
            time.sleep(0.45)
        if not stop_requested:
            driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass


def walk_json(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_json(value)


def is_product_type(item):
    item_type = item.get("@type", "")
    if isinstance(item_type, list):
        return any(str(t).lower() == "product" for t in item_type)
    return str(item_type).lower() == "product"


def price_from_offers(offers):
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if not isinstance(offers, dict):
        return ""
    value = offers.get("price") or offers.get("lowPrice") or ""
    if value == "":
        return ""
    currency = offers.get("priceCurrency", "")
    return clean_text(f"{currency} {value}")


def extract_jsonld_products(soup, base_url):
    results = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for item in walk_json(data):
            if not is_product_type(item):
                continue

            title = clean_text(item.get("name", ""))
            if not title or is_bad_title(title):
                continue

            price = price_from_offers(item.get("offers", {}))

            rating = "Not available"
            aggregate = item.get("aggregateRating", {})
            if isinstance(aggregate, dict) and aggregate.get("ratingValue"):
                rating = str(aggregate["ratingValue"])

            description = clean_text(item.get("description", ""))
            product_url = get_absolute_url(base_url, item.get("url", ""))

            image = item.get("image", "")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url", "")
            image = get_absolute_url(base_url, image) if image else ""

            results.append({
                "title": title,
                "price": price or "Not available",
                "rating": rating,
                "description": description[:600] or "Not available",
                "url": product_url,
                "image": image,
            })
    return results


def prop_value(element):
    if element is None:
        return ""
    return clean_text(element.get("content") or element.get_text())


def extract_microdata_products(soup, base_url):
    results = []
    for product in soup.select("[itemtype*='schema.org/Product'], [itemtype*='/Product']"):
        title = prop_value(product.select_one("[itemprop='name']"))
        if not title or is_bad_title(title):
            continue

        price = prop_value(product.select_one("[itemprop='price']"))
        if price:
            currency = prop_value(product.select_one("[itemprop='priceCurrency']"))
            price = clean_text(f"{currency} {price}")

        rating = prop_value(product.select_one("[itemprop='ratingValue']"))
        description = prop_value(product.select_one("[itemprop='description']"))

        url_element = product.select_one("[itemprop='url']")
        product_url = ""
        if url_element is not None:
            product_url = get_absolute_url(
                base_url,
                url_element.get("href") or url_element.get("content") or ""
            )

        results.append({
            "title": title,
            "price": price or "Not available",
            "rating": rating or "Not available",
            "description": description[:600] or "Not available",
            "url": product_url,
            "image": "",
        })
    return results


def split_lines(node):
    return [
        clean_text(line)
        for line in node.get_text("\n", strip=True).split("\n")
        if clean_text(line)
    ]


def product_keys_in(node):
    keys = set()
    for a in node.find_all("a", href=True):
        if PRODUCT_URL_RE.search(a["href"]):
            keys.add(link_key(a["href"]))
    return keys


def find_card_container(anchor, cache):
    best = None
    if extract_price(anchor.get_text(" ", strip=True)):
        best = anchor

    node = anchor
    for _ in range(8):
        parent = node.parent
        if parent is None or parent.name in ("body", "html", "[document]"):
            break

        keys = cache.get(id(parent))
        if keys is None:
            keys = product_keys_in(parent)
            cache[id(parent)] = keys

        if len(keys) > 1:
            break

        text = parent.get_text(" ", strip=True)
        if len(text) > 1500:
            break

        node = parent
        if extract_price(text):
            best = parent

    return best


def find_card_title(card, link):
    for a in [link] + card.find_all("a", href=True):
        title = clean_text(a.get("title", ""))
        if len(title) >= 8 and not is_bad_title(title):
            return title

    for heading in card.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        title = clean_text(heading.get_text(" ", strip=True))
        if 8 <= len(title) <= 200 and not is_bad_title(title):
            return title

    for img in card.find_all("img"):
        alt = clean_text(img.get("alt", ""))
        if (
            len(alt) >= 10
            and not is_bad_title(alt)
            and alt.lower() not in ("product image", "image", "product")
        ):
            return alt

    for line in split_lines(card):
        if line.lower() in SKIP_LINES:
            continue
        if PRICE_PATTERN.search(line):
            continue
        if not (10 <= len(line) <= 200):
            continue
        if is_bad_title(line):
            continue
        return line

    return ""


def find_card_rating(card, text):
    rating = extract_rating(text)
    if rating != "Not available":
        return rating

    for line in split_lines(card):
        if re.fullmatch(r"[0-5]\.\d", line):
            return line

    return "Not available"


def find_card_image(card, base_url):
    for img in card.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src and not src.startswith("data:"):
            return get_absolute_url(base_url, src)
    return ""


def extract_link_cards(soup, base_url):
    results = []
    seen_keys = set()
    cache = {}

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        if not PRODUCT_URL_RE.search(href):
            continue

        key = link_key(href)
        if key in seen_keys:
            continue

        card = find_card_container(anchor, cache)
        if card is None:
            continue

        text = clean_text(card.get_text(" ", strip=True))
        price = extract_price(text)
        title = find_card_title(card, anchor)

        if not price or not title:
            continue

        seen_keys.add(key)
        detail_lines = [
            line for line in split_lines(card)
            if line != title and line.lower() not in SKIP_LINES
        ]
        description = " | ".join(detail_lines)[:600] or "Not available"

        results.append({
            "title": title,
            "price": price,
            "rating": find_card_rating(card, text),
            "description": description,
            "url": get_absolute_url(base_url, href),
            "image": find_card_image(card, base_url),
        })

    return results


def remove_duplicates(items):
    unique = {}
    for item in items:
        title = clean_text(item.get("title", ""))
        price = clean_text(item.get("price", ""))
        url = clean_text(item.get("url", ""))
        if not title:
            continue
        key = link_key(url) if url else (title.lower(), price.lower())
        if key not in unique:
            unique[key] = item
    return list(unique.values())


def _first_selector_value(node, selectors):
    """Return the first non-empty element and its visible/content text."""
    for selector in selectors or []:
        try:
            element = node.select_one(selector)
            if element:
                value = clean_text(element.get("content") or element.get_text(" ", strip=True))
                if value:
                    return element, value
        except Exception:
            continue
    return None, ""


def extract_configured_cards(soup, base_url):
    """Extract products using the selected store's known card selectors."""
    host = urlparse(base_url).netloc.lower()
    site_key = None
    for key, config in SITE_CONFIG.items():
        domain = urlparse(config["home"]).netloc.lower()
        if host == domain or host.endswith("." + domain):
            site_key = key
            break
    if not site_key:
        return []

    config = SITE_CONFIG[site_key]
    cards = []
    seen_nodes = set()
    for selector in list(config.get("cards", [])) + GENERIC_CARD_SELECTORS:
        try:
            for card in soup.select(selector):
                marker = id(card)
                if marker not in seen_nodes:
                    seen_nodes.add(marker)
                    cards.append(card)
        except Exception:
            continue

    results, seen_products = [], set()
    for card in cards:
        _, title = _first_selector_value(card, config.get("name", []))
        if not title:
            image = card.select_one("img[alt]")
            title = clean_text(image.get("alt", "")) if image else ""
        if not title:
            heading = card.select_one("h2, h3, h4, h5")
            title = clean_text(heading.get_text(" ", strip=True)) if heading else ""
        if is_bad_title(title) or len(title) < 4:
            continue

        _, brand = _first_selector_value(card, config.get("brand", []))
        _, price = _first_selector_value(card, config.get("price", []))
        _, original_price = _first_selector_value(card, config.get("original_price", []))
        _, rating = _first_selector_value(card, config.get("rating", []))

        image_node, _ = _first_selector_value(card, config.get("image", []))
        image_url = ""
        if image_node:
            image_url = (image_node.get("src") or image_node.get("data-src")
                         or image_node.get("data-original") or "")
            if not image_url and image_node.get("srcset"):
                image_url = image_node.get("srcset").split(",")[0].strip().split(" ")[0]
            image_url = get_absolute_url(base_url, image_url)

        link_node, _ = _first_selector_value(card, config.get("link", []))
        product_url = get_absolute_url(base_url, link_node.get("href", "")) if link_node else ""

        # Fallback price/rating detection from the card's visible text.
        card_text = clean_text(card.get_text(" ", strip=True))
        if not price:
            price = extract_price(card_text)
        if not rating or rating == "Not available":
            rating = extract_rating(card_text)
        if not price and not product_url and not image_url:
            continue

        key = (title.lower(), product_url.lower())
        if key in seen_products:
            continue
        seen_products.add(key)
        results.append({
            "title": title,
            "brand": brand or "Not available",
            "price": price or "Not available",
            "original_price": original_price or "Not available",
            "rating": rating or "Not available",
            "description": card_text[:600] or "Not available",
            "url": product_url,
            "image": image_url,
        })

    print(f"Extractor Store-specific cards ({site_key}): {len(results)} products found")
    return results


def extract_products(html, base_url):
    """Run structured-data, store-specific and generic product-card extractors."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    # Structured data is usually the cleanest source when the store provides it.
    for name, function in (
        ("JSON-LD", extract_jsonld_products),
        ("Microdata", extract_microdata_products),
    ):
        try:
            found = remove_duplicates(function(soup, base_url))
            print(f"Extractor {name}: {len(found)} products found")
            if len(found) >= 3:
                candidates.append(found)
            elif found:
                candidates.append(found)
        except Exception as exc:
            print(f"Extractor {name} error: {exc}")

    # Website-specific CSS selectors, then the original generic link/card parser.
    try:
        found = remove_duplicates(extract_configured_cards(soup, base_url))
        if found:
            candidates.append(found)
    except Exception as exc:
        print("Store-specific extractor error:", exc)

    clean_soup = BeautifulSoup(html, "html.parser")
    for tag in clean_soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    try:
        found = remove_duplicates(extract_link_cards(clean_soup, base_url))
        print(f"Extractor Generic product cards: {len(found)} products found")
        if found:
            candidates.append(found)
    except Exception as exc:
        print("Generic extractor error:", exc)

    # Merge records by product URL/title, filling missing fields from other strategies.
    merged = {}
    for group in candidates:
        for item in group:
            key = (item.get("url") or item.get("title", "")).strip().lower()
            if not key:
                continue
            if key not in merged:
                merged[key] = item.copy()
            else:
                for field, value in item.items():
                    if value and value != "Not available" and (
                        not merged[key].get(field) or merged[key].get(field) == "Not available"
                    ):
                        merged[key][field] = value

    return list(merged.values())[:200]


def extract_page_information(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = clean_text(soup.title.get_text()) if soup.title else ""
    headings = []
    for heading in soup.find_all(["h1", "h2", "h3"]):
        text = clean_text(heading.get_text())
        if text and len(text) < 250 and text not in headings:
            headings.append(text)

    paragraphs = []
    for p in soup.find_all("p"):
        text = clean_text(p.get_text())
        if len(text) >= 30 and text not in paragraphs:
            paragraphs.append(text)

    links = []
    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text())
        if len(text) < 5:
            continue
        links.append({
            "title": text[:150],
            "url": get_absolute_url(base_url, a["href"]),
        })
        if len(links) >= 30:
            break

    return {
        "title": title,
        "headings": headings[:20],
        "paragraphs": paragraphs[:10],
        "links": links,
    }


def looks_blocked(html):
    low = html.lower()
    markers = (
        "captcha", "access denied", "unusual traffic",
        "are you a robot", "are you a human",
    )
    return any(marker in low for marker in markers)


