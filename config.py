"""Scraping selectors and product parsing patterns."""

import re


PRICE_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:₹|Rs\.?|INR|\$|USD|€|EUR|£|GBP)\s*[\d,]+(?:\.\d+)?",
    re.IGNORECASE
)


RATING_PATTERN = re.compile(
    r"\b([0-5](?:\.[0-9])?)\s*(?:★|stars?|/5|out of 5)",
    re.IGNORECASE
)


PRODUCT_URL_RE = re.compile(
    r"/(?:p|dp|pd|product|products|item|itm|buy)/",
    re.IGNORECASE
)


PRODUCT_LINK_SELECTOR = ", ".join(
    f"a[href*='{part}']"
    for part in ("/p/", "/dp/", "/pd/", "/product/", "/products/", "/itm/", "/item/")
)


KNOWN_SEARCH_URLS = {
    "flipkart.com": "https://www.flipkart.com/search?q={q}",
    "amazon.in": "https://www.amazon.in/s?k={q}",
    "amazon.com": "https://www.amazon.com/s?k={q}",
    "snapdeal.com": "https://www.snapdeal.com/search?keyword={q}",
    "ebay.com": "https://www.ebay.com/sch/i.html?_nkw={q}",
    "ajio.com": "https://www.ajio.com/search/?text={q}",
    "meesho.com": "https://www.meesho.com/search?q={q}",
    "nykaa.com": "https://www.nykaa.com/search/result/?q={q}",
}


SITE_CONFIG = {
    "myntra": {
        "home": "https://www.myntra.com/",
        "search": "https://www.myntra.com/{slug}",
        "cards": [".product-base", "li.product-base"],
        "name": [".product-product", ".product-product-name", "h4"],
        "brand": [".product-brand", "h3"],
        "price": [".product-discountedPrice", ".product-price"],
        "original_price": [".product-strike", ".product-original-price"],
        "rating": [".product-ratingsContainer", ".product-ratings"],
        "image": ["img.img-responsive", "img"],
        "link": ["a[href]"],
    },
    "flipkart": {
        "home": "https://www.flipkart.com/",
        "search": "https://www.flipkart.com/search?q={query}",
        "cards": ["div[data-id]", "._1AtVbE"],
        "name": ["._4rR01T", ".s1Q9rs", "a[title]"],
        "brand": [],
        "price": ["._30jeq3", "._1_WHN1"],
        "original_price": ["._3I9_wc", "._27UcVY"],
        "rating": ["._3LWZlK", "._2_R_DZ"],
        "image": ["img"],
        "link": ["a[href]"],
    },
    "amazon_in": {
        "home": "https://www.amazon.in/",
        "search": "https://www.amazon.in/s?k={query}",
        "cards": ["div[data-component-type='s-search-result']"],
        "name": ["h2 a span", "h2"],
        "brand": [],
        "price": [".a-price .a-offscreen"],
        "original_price": [".a-text-price .a-offscreen"],
        "rating": ["span.a-icon-alt"],
        "image": ["img.s-image"],
        "link": ["h2 a", "a.a-link-normal"],
    },
    "amazon_us": {
        "home": "https://www.amazon.com/",
        "search": "https://www.amazon.com/s?k={query}",
        "cards": ["div[data-component-type='s-search-result']"],
        "name": ["h2 a span", "h2"],
        "brand": [],
        "price": [".a-price .a-offscreen"],
        "original_price": [".a-text-price .a-offscreen"],
        "rating": ["span.a-icon-alt"],
        "image": ["img.s-image"],
        "link": ["h2 a", "a.a-link-normal"],
    },
    "ajio": {
        "home": "https://www.ajio.com/",
        "search": "https://www.ajio.com/search/?text={query}",
        "cards": [".item", ".rilrtl-products-list__item"],
        "name": [".nameCls", ".title"],
        "brand": [".brand"],
        "price": [".price", ".offer-pricе"],
        "original_price": [".orginal-price", ".original-price"],
        "rating": [],
        "image": ["img"],
        "link": ["a[href]"],
    },
    "snapdeal": {
        "home": "https://www.snapdeal.com/",
        "search": "https://www.snapdeal.com/search?keyword={query}",
        "cards": [".product-tuple-listing"],
        "name": [".product-title"],
        "brand": [],
        "price": [".product-price"],
        "original_price": [".product上-price", ".product-desc-price"],
        "rating": [".filled-stars"],
        "image": ["img.product-image"],
        "link": ["a[href]"],
    },
    "ebay": {
        "home": "https://www.ebay.com/",
        "search": "https://www.ebay.com/sch/i.html?_nkw={query}",
        "cards": ["li.s-item"],
        "name": [".s-item__title"],
        "brand": [],
        "price": [".s-item__price"],
        "original_price": [],
        "rating": [".b-starrating"],
        "image": ["img.s-item__image-img"],
        "link": [".s-item__link"],
    },
    "meesho": {
        "home": "https://www.meesho.com/",
        "search": "https://www.meesho.com/search?q={query}",
        "cards": ["div[class*='ProductCard']", "a[href*='/']"],
        "name": ["p", "h5"],
        "brand": [],
        "price": ["h5"],
        "original_price": [],
        "rating": [],
        "image": ["img"],
        "link": ["a[href]"],
    },
    "nykaa": {
        "home": "https://www.nykaa.com/",
        "search": "https://www.nykaa.com/search/result/?q={query}",
        "cards": ["div[class*='productWrapper']", "div[class*='product-listing']"],
        "name": ["div[class*='productTitle']", "h3"],
        "brand": [],
        "price": ["span[class*='final-price']", "span[class*='price']"],
        "original_price": ["span[class*='old-price']"],
        "rating": ["span[class*='rating']"],
        "image": ["img"],
        "link": ["a[href]"],
    },
}


GENERIC_CARD_SELECTORS = [
    "[data-testid*='product']", "[class*='product-card']",
    "[class*='productCard']", "[class*='product-base']",
    "[class*='product-item']", "[class*='ProductCard']",
    "li[class*='product']"
]


BAD_TITLES = {
    "terms", "terms of use", "privacy", "privacy policy", "contact us",
    "about us", "help", "customer service", "login", "log in", "sign in",
    "register", "sign up", "careers", "sell", "become a seller",
    "advertise", "download app", "gift cards", "track order", "wishlist",
    "cart", "home", "categories", "all categories", "most loved",
    "most-loved", "top rated", "top deals", "shop now", "view all",
    "see all", "electronics", "fashion", "grocery", "sponsored",
}


SKIP_LINES = {
    "sponsored", "ad", "add to compare", "compare", "bestseller",
    "best seller", "assured", "f-assured", "flipkart assured",
    "wishlist", "free delivery", "new", "trending", "hot deal",
    "limited time deal", "save extra", "special price",
}
