"""Tkinter interface and application workflow."""

import csv
import json
import os
import threading
import time
import webbrowser
from urllib.parse import urlparse

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import environment, scraper
from .scraper import (
    clean_text, dismiss_popups, extract_page_information, extract_products,
    is_valid_url, looks_blocked, normalize_url, parse_budget_constraint,
    parse_numeric_price, parse_numeric_rating, perform_search, scroll_page,
    start_driver, wait_for_page_ready, wait_for_product_links,
)
from .themes import THEME

products = []
displayed_products = []
current_selected_product = None

root = None
url_entry = None
search_entry = None
search_button = None
stop_button = None
clear_button = None
status_badge_icon = None
status_badge_text = None
stats_counter_badge = None
progress_bar = None
filter_entry = None
product_tree = None
details_text = None
btn_open_browser = None
btn_copy_url = None
btn_copy_details = None


def bring_gui_to_front():
    def _raise():
        try:
            if root and root.winfo_exists():
                root.deiconify()
                root.lift()
                root.attributes("-topmost", True)
                root.focus_force()
                root.after(400, lambda: root.attributes("-topmost", False))
        except Exception:
            pass

    if root and root.winfo_exists():
        root.after(0, _raise)


def search_website_trigger():
    global products, displayed_products, current_selected_product

    url = normalize_url(url_entry.get())
    query = search_entry.get().strip()

    if not url:
        messagebox.showerror("Validation Error", "Please provide a valid website URL.")
        return

    if not is_valid_url(url):
        messagebox.showerror(
            "Invalid URL",
            "Please enter a valid website address.\n\nExample:\nhttps://www.flipkart.com/"
        )
        return

    products.clear()
    displayed_products.clear()
    current_selected_product = None
    scraper.stop_requested = False
    clear_results_ui()

    set_ui_scraping_state(active=True)
    update_status("Initializing Selenium Browser...", state="working")

    thread = threading.Thread(
        target=perform_scraping_worker, args=(url, query), daemon=True
    )
    thread.start()


def stop_scraping_trigger():
    """Stop the active scrape and release the Selenium browser session."""
    if scraper.stop_requested:
        return
    scraper.stop_requested = True
    update_status("Stop requested — closing the browser session...", state="warning")
    try:
        stop_button.config(state="disabled", text="STOPPING...", bg=THEME["danger_hover"])
    except Exception:
        pass
    # Quitting the active driver interrupts a pending Selenium navigation/wait.
    # The worker's finally block restores the Start/Stop controls.
    try:
        active_driver = scraper.driver
        if active_driver is not None:
            active_driver.quit()
    except Exception:
        pass


def perform_scraping_worker(url, query):
    global products

    try:
        update_status("Opening browser window...", state="working")
        start_driver()
        bring_gui_to_front()
        if scraper.stop_requested:
            return

        if query:
            update_status(f"Searching for '{query}'...", state="working")
        else:
            update_status("Navigating to target page...", state="working")

        search_terms, max_price = parse_budget_constraint(query)
        final_url = perform_search(url, search_terms)
        if scraper.stop_requested:
            return

        update_status("Waiting for dynamic elements to appear...", state="working")
        wait_for_page_ready()
        if scraper.stop_requested:
            return
        wait_for_product_links(timeout=10)
        if scraper.stop_requested:
            return

        update_status("Scrolling page to trigger lazy-loaded cards...", state="working")
        dismiss_popups()
        scroll_page()
        if scraper.stop_requested:
            return
        time.sleep(0.5)
        if scraper.stop_requested:
            return

        html = scraper.driver.page_source

        update_status("Parsing DOM structure with BeautifulSoup...", state="working")
        found = extract_products(html, final_url)

        # Enforce the requested maximum price locally. Search engines may ignore
        # words such as "under 50000", so never trust the website query alone.
        if max_price is not None:
            before_filter = len(found)
            found = [
                item for item in found
                if 0 <= parse_numeric_price(item.get("price", "")) < max_price
            ]
            excluded = before_filter - len(found)
            currency_label = "₹" if urlparse(final_url).netloc.lower().endswith(
                (".in", "flipkart.com", "myntra.com", "ajio.com", "snapdeal.com", "meesho.com", "nykaa.com")
            ) else ""
            budget_note = (
                f"Maximum price applied: {currency_label}{max_price:,.0f}. "
                f"{excluded} product(s) above the limit or without a readable price excluded."
            )
        else:
            budget_note = ""

        if found:
            products.extend(found)
            root.after(0, lambda: on_scraping_success(len(products), budget_note))
        elif max_price is not None and before_filter if 'before_filter' in locals() else False:
            root.after(0, lambda: on_scraping_success(0, budget_note))
        else:
            try:
                with open("debug_page.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

            if looks_blocked(html):
                root.after(0, lambda: update_status("Security verification / CAPTCHA triggered.", state="danger"))
            else:
                root.after(0, lambda: update_status("No product patterns detected on this page.", state="warning"))

            page_info = extract_page_information(html, final_url)
            root.after(0, lambda: display_generic_page_info(page_info))

    except Exception as e:
        error_message = str(e)
        print("SCRAPING EXCEPTION:", repr(e))
        if scraper.stop_requested:
            root.after(0, lambda: update_status("Scraping stopped.", state="warning"))
        else:
            root.after(0, lambda msg=error_message: on_scraping_error(msg))

    finally:
        root.after(0, lambda: set_ui_scraping_state(active=False))
        bring_gui_to_front()


def on_scraping_success(count, budget_note=""):
    if count:
        message = f"Extraction successful: {count} products captured."
    else:
        message = "No products matched the requested price limit."
    if budget_note:
        message += " " + budget_note
    update_status(message, state="success" if count else "warning")
    update_stats_badge(f"📦 {count} Items Extracted")
    populate_product_tree(products)
    if not count and budget_note:
        show_empty_details()


def on_scraping_error(error_msg):
    update_status("Scraping halted due to an error.", state="danger")
    messagebox.showerror(
        "Scraper Execution Notice",
        "Could not complete web extraction.\n\n"
        f"Details: {error_msg}\n\n"
        "Common Causes:\n"
        "• Network timeout or connection drop\n"
        "• Bot-detection or CAPTCHA challenge\n"
        "• Chrome or ChromeDriver update mismatch"
    )


def make_hover_button(
    parent, text, command, bg, fg="white", hover_bg=None,
    font=("Segoe UI", 10, "bold"), padx=16, pady=8, **kwargs
):
    """Factory creating sleek Tkinter buttons with mouse hover animations."""
    if hover_bg is None:
        hover_bg = bg

    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=hover_bg,
        activeforeground=fg,
        font=font,
        relief="flat",
        cursor="hand2",
        bd=0,
        padx=padx,
        pady=pady,
        **kwargs
    )

    def on_enter(e):
        if btn["state"] != "disabled":
            btn.config(bg=hover_bg)

    def on_leave(e):
        if btn["state"] != "disabled":
            btn.config(bg=bg)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


def update_status(message, state="normal"):
    """
    Updates the interactive status badge with colors and icons:
    - 'normal' / 'ready': Green dot
    - 'working': Pulsing cyan dot
    - 'success': Bright emerald
    - 'warning': Amber dot
    - 'danger': Red dot
    """
    if not root or not root.winfo_exists():
        return

    icons = {
        "normal": ("●", THEME["success"]),
        "working": ("◐", THEME["accent_cyan"]),
        "success": ("✓", THEME["success"]),
        "warning": ("▲", THEME["warning"]),
        "danger": ("✕", THEME["danger"]),
    }
    icon, color = icons.get(state, ("●", THEME["text_muted"]))

    def _apply():
        try:
            status_badge_icon.config(text=icon, fg=color)
            status_badge_text.config(text=message, fg=THEME["text_main"])
        except Exception:
            pass

    root.after(0, _apply)


def update_stats_badge(text):
    if stats_counter_badge and stats_counter_badge.winfo_exists():
        stats_counter_badge.config(text=text)


def set_ui_scraping_state(active=True):
    """Enables/disables scraping controls and toggles the progress animation."""
    if active:
        search_button.config(state="disabled", bg=THEME["bg_subpanel"], text="SCRAPING...")
        stop_button.config(
            state="normal", text="■ STOP SCRAPING",
            bg=THEME["danger"], fg="#ffffff"
        )
        progress_bar.start(12)
        progress_bar.pack(fill="x", side="bottom")
    else:
        search_button.config(state="normal", bg=THEME["primary"], text="🔍 START SCRAPING")
        stop_button.config(
            state="disabled", text="■ STOP SCRAPING",
            bg=THEME["bg_subpanel"], fg=THEME["text_muted"]
        )
        progress_bar.stop()
        progress_bar.pack_forget()


def populate_product_tree(items):
    """Fill the table from highest to lowest price; unknown prices remain last."""
    global displayed_products
    known_prices = [
        item for item in items
        if parse_numeric_price(item.get("price", "")) >= 0
    ]
    unknown_prices = [
        item for item in items
        if parse_numeric_price(item.get("price", "")) < 0
    ]
    displayed_products = sorted(
        known_prices,
        key=lambda item: parse_numeric_price(item.get("price", "")),
        reverse=True
    ) + unknown_prices

    for row in product_tree.get_children():
        product_tree.delete(row)

    for i, prod in enumerate(displayed_products, start=1):
        tag = "evenrow" if i % 2 == 0 else "oddrow"
        title = prod.get("title", "Untitled")
        price = prod.get("price", "Not available")
        rating = prod.get("rating", "Not available")
        if rating != "Not available" and not rating.startswith("★"):
            rating_display = f"★ {rating}"
        else:
            rating_display = rating

        product_tree.insert(
            "",
            "end",
            iid=str(i - 1),
            values=(f"{i:02d}", title, price, rating_display),
            tags=(tag,)
        )

    if displayed_products:
        product_tree.selection_set("0")
        product_tree.focus("0")
        on_tree_select(None)
    else:
        show_empty_details()


def filter_products(event=None):
    """Instant search & filter through already extracted items."""
    query = filter_entry.get().strip().lower()
    if not query:
        populate_product_tree(products)
        return

    filtered = [
        p for p in products
        if query in p.get("title", "").lower()
        or query in p.get("price", "").lower()
        or query in p.get("description", "").lower()
    ]
    populate_product_tree(filtered)
    update_stats_badge(f"🔍 {len(filtered)} / {len(products)} Matched")


def sort_tree_column(col_index, reverse=True):
    """Click on a column header to sort items ascending/descending."""
    global displayed_products

    if not displayed_products:
        return

    if col_index == 0:  # Number
        displayed_products.sort(key=lambda x: products.index(x) if x in products else 0, reverse=reverse)
    elif col_index == 1:  # Title
        displayed_products.sort(key=lambda x: x.get("title", "").lower(), reverse=reverse)
    elif col_index == 2:  # Price
        displayed_products.sort(key=lambda x: parse_numeric_price(x.get("price", "")), reverse=reverse)
    elif col_index == 3:  # Rating
        displayed_products.sort(key=lambda x: parse_numeric_rating(x.get("rating", "")), reverse=reverse)

    # Re-insert into tree
    for row in product_tree.get_children():
        product_tree.delete(row)

    for i, prod in enumerate(displayed_products, start=1):
        tag = "evenrow" if i % 2 == 0 else "oddrow"
        rating = prod.get("rating", "Not available")
        rating_display = f"★ {rating}" if (rating != "Not available" and not rating.startswith("★")) else rating

        product_tree.insert(
            "",
            "end",
            iid=str(i - 1),
            values=(f"{i:02d}", prod.get("title", ""), prod.get("price", ""), rating_display),
            tags=(tag,)
        )

    # Toggle reverse sort for next click
    product_tree.heading(
        f"col_{col_index}",
        command=lambda: sort_tree_column(col_index, not reverse)
    )

    if displayed_products:
        product_tree.selection_set("0")
        on_tree_select(None)


def on_tree_select(event=None):
    """Triggered when user clicks a row in the product table."""
    global current_selected_product

    selected = product_tree.selection()
    if not selected:
        return

    try:
        index = int(selected[0])
        if index < len(displayed_products):
            current_selected_product = displayed_products[index]
            render_product_details(current_selected_product)
    except Exception as e:
        print("Selection error:", e)


def render_product_details(product):
    """Formats and prints rich interactive details into the details pane."""
    details_text.config(state="normal")
    details_text.delete("1.0", tk.END)

    title = product.get("title", "Untitled Product")
    price = product.get("price", "Not available")
    rating = product.get("rating", "Not available")
    brand = product.get("brand", "Not available")
    original_price = product.get("original_price", "Not available")
    url = product.get("url", "")
    desc = product.get("description", "No extended description available.")

    # 1. Product Title
    details_text.insert(tk.END, f"{title}\n\n", "title")

    # 2. Price and Rating Badges
    details_text.insert(tk.END, " PRICE  ", "badge_price_lbl")
    details_text.insert(tk.END, f" {price}   ", "badge_price_val")

    details_text.insert(tk.END, " RATING  ", "badge_rating_lbl")
    star_str = f" ★ {rating} / 5.0" if rating != "Not available" else " Not available"
    details_text.insert(tk.END, f" {star_str}\n\n", "badge_rating_val")
    details_text.insert(tk.END, f"BRAND: {brand}\n", "body_text")
    details_text.insert(tk.END, f"ORIGINAL PRICE: {original_price}\n\n", "body_text")

    # 3. Direct Link Section
    details_text.insert(tk.END, "PRODUCT URL\n", "section_head")
    if url:
        details_text.insert(tk.END, f"{url}\n", ("link", "url_text"))
    else:
        details_text.insert(tk.END, "Direct link not detected.\n", "muted")

    details_text.insert(tk.END, "\n" + "─" * 50 + "\n\n", "divider")

    # 4. Specifications / Description
    details_text.insert(tk.END, "KEY SPECIFICATIONS & ATTRIBUTES\n", "section_head")
    if " | " in desc:
        items = desc.split(" | ")
        for item in items:
            item_clean = clean_text(item)
            if item_clean:
                details_text.insert(tk.END, f" •  {item_clean}\n", "spec_bullet")
    else:
        details_text.insert(tk.END, f"{desc}\n", "body_text")

    details_text.config(state="disabled")

    # Update Action Buttons
    has_url = bool(url)
    btn_open_browser.config(state="normal" if has_url else "disabled")
    btn_copy_url.config(state="normal" if has_url else "disabled")
    btn_copy_details.config(state="normal")


def show_empty_details():
    details_text.config(state="normal")
    details_text.delete("1.0", tk.END)
    details_text.insert(
        tk.END,
        "\n\n\n\n\n        ✨ Select a product on the left to inspect\n"
        "           specifications, live pricing, and direct link.",
        "placeholder"
    )
    details_text.config(state="disabled")
    btn_open_browser.config(state="disabled")
    btn_copy_url.config(state="disabled")
    btn_copy_details.config(state="disabled")


def display_generic_page_info(page_info):
    details_text.config(state="normal")
    details_text.delete("1.0", tk.END)

    title = page_info.get("title", "Generic Webpage")
    headings = page_info.get("headings", [])
    paragraphs = page_info.get("paragraphs", [])

    details_text.insert(tk.END, f"WEBPAGE SUMMARY: {title}\n\n", "title")
    details_text.insert(tk.END, "Notice: No structured product catalog was found.\n", "warning")
    details_text.insert(tk.END, "A snapshot of the raw page was saved to debug_page.html\n\n", "muted")

    if headings:
        details_text.insert(tk.END, "Detected Section Headings:\n", "section_head")
        for h in headings:
            details_text.insert(tk.END, f" • {h}\n", "spec_bullet")
        details_text.insert(tk.END, "\n")

    if paragraphs:
        details_text.insert(tk.END, "Extracted Paragraphs:\n", "section_head")
        for p in paragraphs:
            details_text.insert(tk.END, f"{p}\n\n", "body_text")

    details_text.config(state="disabled")


def open_selected_in_browser():
    if current_selected_product and current_selected_product.get("url"):
        webbrowser.open(current_selected_product["url"])
    else:
        messagebox.showinfo("Notice", "No product URL is available.")


def copy_product_url():
    if current_selected_product and current_selected_product.get("url"):
        root.clipboard_clear()
        root.clipboard_append(current_selected_product["url"])
        update_status("Product link copied to clipboard!", state="success")
    else:
        messagebox.showinfo("Notice", "No product URL to copy.")


def copy_product_details():
    if current_selected_product:
        text = (
            f"Title: {current_selected_product.get('title')}\n"
            f"Price: {current_selected_product.get('price')}\n"
            f"Rating: {current_selected_product.get('rating')}\n"
            f"URL: {current_selected_product.get('url')}\n"
            f"Description: {current_selected_product.get('description')}\n"
        )
        root.clipboard_clear()
        root.clipboard_append(text)
        update_status("All product details copied to clipboard!", state="success")


def export_data(format_type="csv"):
    """Export captured products to CSV or JSON format."""
    if not products:
        messagebox.showinfo("Export", "No products available to export.")
        return

    default_name = f"scraped_products_{int(time.time())}.{format_type}"
    file_path = filedialog.asksaveasfilename(
        defaultextension=f".{format_type}",
        initialfile=default_name,
        filetypes=[(f"{format_type.upper()} Files", f"*.{format_type}")]
    )

    if not file_path:
        return

    try:
        if format_type == "csv":
            keys = ["title", "brand", "price", "original_price", "rating", "url", "image", "description"]
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(products)
        elif format_type == "json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(products, f, indent=2, ensure_ascii=False)

        update_status(f"Exported {len(products)} products to {os.path.basename(file_path)}", state="success")
        messagebox.showinfo("Export Successful", f"Successfully exported data to:\n{file_path}")
    except Exception as e:
        messagebox.showerror("Export Error", f"Failed to export data: {e}")


def clear_results_ui():
    global current_selected_product
    current_selected_product = None
    for row in product_tree.get_children():
        product_tree.delete(row)
    show_empty_details()
    update_stats_badge("📦 0 Items Extracted")


def clear_all():
    global products, displayed_products, current_selected_product
    products.clear()
    displayed_products.clear()
    current_selected_product = None

    url_entry.delete(0, tk.END)
    search_entry.delete(0, tk.END)
    filter_entry.delete(0, tk.END)
    clear_results_ui()
    update_status("Ready. Enter target URL or select a preset.", state="normal")


def apply_preset(url, default_search=""):
    """Quick Preset Button click handler."""
    url_entry.delete(0, tk.END)
    url_entry.insert(0, url)
    if default_search:
        search_entry.delete(0, tk.END)
        search_entry.insert(0, default_search)
    search_entry.focus_set()
    update_status(f"Loaded preset for {urlparse(url).netloc}", state="normal")


def close_application():
    try:
        if scraper.driver is not None:
            scraper.driver.quit()
    except Exception:
        pass
    if root and root.winfo_exists():
        root.destroy()


def build_gui():
    global root, url_entry, search_entry, search_button, stop_button, clear_button
    global status_badge_icon, status_badge_text, stats_counter_badge
    global progress_bar, filter_entry, product_tree, details_text
    global btn_open_browser, btn_copy_url, btn_copy_details
    
    root = tk.Tk()
    root.title("Dynamic Web Scraping Studio • Pro Edition")

    environment.SCREEN_W = root.winfo_screenwidth()
    environment.SCREEN_H = root.winfo_screenheight()
    environment.GUI_WIDTH = environment.SCREEN_W
    gui_height = max(700, environment.SCREEN_H - 70)

    window_width = max(1100, environment.SCREEN_W - 30)
    window_height = max(700, environment.SCREEN_H - 80)
    x_pos = max(0, (environment.SCREEN_W - window_width) // 2)
    y_pos = max(0, (environment.SCREEN_H - window_height) // 2)
    root.geometry(f"{window_width}x{window_height}+{x_pos}+{y_pos}")
    root.minsize(1100, 700)
    root.configure(bg=THEME["bg_dark"])

    # Configure TTK Theme & Styles
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        "Treeview",
        background=THEME["bg_panel"],
        foreground=THEME["text_main"],
        fieldbackground=THEME["bg_panel"],
        rowheight=32,
        font=("Segoe UI", 10),
        borderwidth=0
    )
    style.configure(
        "Treeview.Heading",
        background=THEME["bg_subpanel"],
        foreground=THEME["text_muted"],
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        padding=(8, 8)
    )
    style.map(
        "Treeview.Heading",
        background=[("active", THEME["bg_hover"])],
        foreground=[("active", THEME["text_main"])]
    )
    style.map(
        "Treeview",
        background=[("selected", THEME["tree_select"])],
        foreground=[("selected", "#ffffff")]
    )

    style.configure(
        "Horizontal.TProgressbar",
        background=THEME["accent_cyan"],
        troughcolor=THEME["bg_panel"],
        borderwidth=0,
        thickness=4
    )

    # --------------------------------------------------------
    # 1. TOP HEADER BANNER (Branding, Status Pill, Stats)
    # --------------------------------------------------------
    header_container = tk.Frame(root, bg=THEME["bg_dark"])
    header_container.pack(fill="x", padx=16, pady=(12, 6))

    # Left: App Brand & Subtitle
    brand_frame = tk.Frame(header_container, bg=THEME["bg_dark"])
    brand_frame.pack(side="left")

    title_box = tk.Frame(brand_frame, bg=THEME["bg_dark"])
    title_box.pack(anchor="w")

    tk.Label(
        title_box,
        text="⚡",
        bg=THEME["bg_dark"],
        fg=THEME["warning"],
        font=("Segoe UI", 18, "bold")
    ).pack(side="left", padx=(0, 6))

    tk.Label(
        title_box,
        text="SCRAPER",
        bg=THEME["bg_dark"],
        fg="#22c7f2",
        font=("Segoe UI", 16, "bold")
    ).pack(side="left", padx=(0, 5))

    tk.Label(
        title_box,
        text="STUDIO",
        bg=THEME["bg_dark"],
        fg="#ff4568",
        font=("Segoe UI", 16, "bold")
    ).pack(side="left")

    tk.Label(
        title_box,
        text=" PRO",
        bg="#7c3aed",
        fg="white",
        font=("Segoe UI", 8, "bold"),
        padx=7,
        pady=3
    ).pack(side="left", padx=8)

    tk.Label(
        brand_frame,
        text="• Multi-Strategy Extraction    • Selenium & BeautifulSoup    • E-Commerce Automation",
        bg=THEME["bg_dark"],
        fg=THEME["text_dim"],
        font=("Segoe UI", 9)
    ).pack(anchor="w", pady=(2, 0))

    # Right: Status Pill & Stats Chip
    badges_frame = tk.Frame(header_container, bg=THEME["bg_dark"])
    badges_frame.pack(side="right", pady=4)

    # Live Status Pill
    status_pill = tk.Frame(badges_frame, bg=THEME["bg_panel"], padx=10, pady=5, bd=1, relief="solid")
    status_pill.pack(side="left", padx=4)

    status_badge_icon = tk.Label(status_pill, text="●", bg=THEME["bg_panel"], fg=THEME["success"], font=("Segoe UI", 10))
    status_badge_icon.pack(side="left", padx=(0, 5))

    status_badge_text = tk.Label(status_pill, text="Ready", bg=THEME["bg_panel"], fg=THEME["text_main"], font=("Segoe UI", 9, "bold"))
    status_badge_text.pack(side="left")

    # Item Counter Badge
    stats_counter_badge = tk.Label(
        badges_frame,
        text="📦 0 Items Extracted",
        bg=THEME["bg_subpanel"],
        fg=THEME["accent_cyan"],
        font=("Segoe UI", 9, "bold"),
        padx=10,
        pady=5
    )
    stats_counter_badge.pack(side="left", padx=4)

    # --------------------------------------------------------
    # 2. QUICK STORE PRESETS BAR
    # --------------------------------------------------------
    presets_bar = tk.Frame(root, bg=THEME["bg_dark"])
    presets_bar.pack(fill="x", padx=16, pady=(4, 8))

    tk.Label(
        presets_bar,
        text="QUICK PRESETS:",
        bg=THEME["bg_dark"],
        fg=THEME["text_dim"],
        font=("Segoe UI", 8, "bold")
    ).pack(side="left", padx=(0, 6))

    stores = [
        ("🛍️ Flipkart", "https://www.flipkart.com/", "laptop under 50000"),
        ("♧ Myntra", "https://www.myntra.com/", "men sneakers"),
        ("🛒 Ajio", "https://www.ajio.com/", "men shoes"),
        ("📦 Amazon India", "https://www.amazon.in/", "smart watch under 5000"),
        ("🌐 Amazon US", "https://www.amazon.com/", "smart watch"),
        ("🏷️ Snapdeal", "https://www.snapdeal.com/", "running shoes"),
        ("🛒 eBay", "https://www.ebay.com/", "vintage watch"),
        ("🛍️ Meesho", "https://www.meesho.com/", "women kurti"),
        ("✦ Nykaa", "https://www.nykaa.com/", "face wash"),
    ]

    preset_accents = [
        "#3b82f6", "#ec4899", "#f59e0b", "#eab308", "#06b6d4",
        "#ef4444", "#60a5fa", "#a78bfa", "#ec4899"
    ]
    for preset_index, (label, preset_url, query_hint) in enumerate(stores):
        accent = preset_accents[preset_index % len(preset_accents)]
        btn_preset = tk.Button(
            presets_bar,
            text=label,
            bg=THEME["bg_dark"],
            fg=accent,
            activebackground=accent,
            activeforeground="#ffffff",
            font=("Segoe UI", 8, "bold"),
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=accent,
            highlightcolor=accent,
            padx=9,
            pady=4,
            cursor="hand2",
            command=lambda u=preset_url, q=query_hint: apply_preset(u, q)
        )
        btn_preset.pack(side="left", padx=3)

        def make_preset_hover(button, color):
            button.bind("<Enter>", lambda e, b=button, c=color: b.config(
                bg=c, fg="#ffffff"
            ))
            button.bind("<Leave>", lambda e, b=button, c=color: b.config(
                bg=THEME["bg_dark"], fg=c
            ))
        make_preset_hover(btn_preset, accent)

    # --------------------------------------------------------
    # 3. INTERACTIVE CONTROL CENTER (URL, Query, Actions)
    # --------------------------------------------------------
    control_card = tk.Frame(root, bg=THEME["bg_panel"], padx=14, pady=12)
    control_card.pack(fill="x", padx=16, pady=4)

    # Row 0: Target Website URL
    tk.Label(
        control_card,
        text="Target Website URL:",
        bg=THEME["bg_panel"],
        fg=THEME["text_muted"],
        font=("Segoe UI", 9, "bold")
    ).grid(row=0, column=0, sticky="w", padx=4, pady=(2, 4))

    url_frame = tk.Frame(control_card, bg=THEME["bg_subpanel"], padx=6, pady=4)
    url_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 8))

    url_entry = tk.Entry(
        url_frame,
        bg=THEME["bg_subpanel"],
        fg=THEME["text_main"],
        insertbackground="white",
        font=("Segoe UI", 11),
        relief="flat",
        bd=0
    )
    url_entry.pack(fill="x", expand=True)
    url_entry.insert(0, "https://www.flipkart.com/")

    # Row 2: Search Query & Action Buttons
    tk.Label(
        control_card,
        text="Search Query / Keyword (optional):",
        bg=THEME["bg_panel"],
        fg=THEME["text_muted"],
        font=("Segoe UI", 9, "bold")
    ).grid(row=2, column=0, sticky="w", padx=4, pady=(2, 4))

    search_frame = tk.Frame(control_card, bg=THEME["bg_subpanel"], padx=6, pady=4)
    search_frame.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 4))

    search_entry = tk.Entry(
        search_frame,
        bg=THEME["bg_subpanel"],
        fg=THEME["text_main"],
        insertbackground="white",
        font=("Segoe UI", 11),
        relief="flat",
        bd=0
    )
    search_entry.pack(fill="x", expand=True)
    search_entry.insert(0, "laptop under 50000")
    search_entry.bind("<Return>", lambda e: search_website_trigger())

    # Buttons Container
    btn_group = tk.Frame(control_card, bg=THEME["bg_panel"])
    btn_group.grid(row=3, column=1, sticky="e", padx=4)

    search_button = make_hover_button(
        btn_group,
        text="🔍 START SCRAPING",
        command=search_website_trigger,
        bg=THEME["primary"],
        hover_bg=THEME["primary_hover"],
        font=("Segoe UI", 10, "bold"),
        padx=18,
        pady=7
    )
    search_button.pack(side="left", padx=4)

    stop_button = make_hover_button(
        btn_group,
        text="■ STOP SCRAPING",
        command=stop_scraping_trigger,
        bg=THEME["bg_subpanel"],
        hover_bg=THEME["danger"],
        font=("Segoe UI", 10, "bold"),
        padx=14,
        pady=7
    )
    stop_button.pack(side="left", padx=4)
    stop_button.config(state="disabled")

    clear_button = make_hover_button(
        btn_group,
        text="🗑️ Clear",
        command=clear_all,
        bg=THEME["bg_subpanel"],
        hover_bg=THEME["bg_hover"],
        font=("Segoe UI", 10),
        padx=14,
        pady=7
    )
    clear_button.pack(side="left", padx=4)

    control_card.columnconfigure(0, weight=1)

    # Indeterminate progress bar (packed during execution)
    progress_bar = ttk.Progressbar(root, mode="indeterminate", style="Horizontal.TProgressbar")

    # --------------------------------------------------------
    # 4. MAIN SPLIT WORKSPACE (Results Table + Detail Inspector)
    # --------------------------------------------------------
    workspace_frame = tk.Frame(root, bg=THEME["bg_dark"])
    workspace_frame.pack(fill="both", expand=True, padx=16, pady=(8, 12))

    # ---- LEFT PANE: EXTRACTED PRODUCTS DATA TABLE ----
    left_pane = tk.Frame(workspace_frame, bg=THEME["bg_panel"])
    left_pane.pack(side="left", fill="both", expand=True, padx=(0, 6))

    # Header with Title and Live Filter Search Box
    left_header = tk.Frame(left_pane, bg=THEME["bg_panel"], padx=10, pady=8)
    left_header.pack(fill="x")

    tk.Label(
        left_header,
        text="EXTRACTED PRODUCTS",
        bg=THEME["bg_panel"],
        fg=THEME["text_main"],
        font=("Segoe UI", 11, "bold")
    ).pack(side="left")

    # Export Buttons
    btn_export_csv = make_hover_button(
        left_header,
        text="CSV",
        command=lambda: export_data("csv"),
        bg=THEME["bg_subpanel"],
        hover_bg=THEME["success_hover"],
        font=("Segoe UI", 8, "bold"),
        padx=8,
        pady=3
    )
    btn_export_csv.pack(side="right", padx=2)

    btn_export_json = make_hover_button(
        left_header,
        text="JSON",
        command=lambda: export_data("json"),
        bg=THEME["bg_subpanel"],
        hover_bg=THEME["accent_purple_hover"],
        font=("Segoe UI", 8, "bold"),
        padx=8,
        pady=3
    )
    btn_export_json.pack(side="right", padx=2)

    # Filter Entry Bar
    filter_bar = tk.Frame(left_pane, bg=THEME["bg_subpanel"], padx=8, pady=4)
    filter_bar.pack(fill="x", padx=10, pady=(0, 6))

    tk.Label(
        filter_bar,
        text="🔎",
        bg=THEME["bg_subpanel"],
        fg=THEME["text_muted"],
        font=("Segoe UI", 9)
    ).pack(side="left", padx=(0, 4))

    filter_entry = tk.Entry(
        filter_bar,
        bg=THEME["bg_subpanel"],
        fg=THEME["text_main"],
        insertbackground="white",
        font=("Segoe UI", 9),
        relief="flat",
        bd=0
    )
    filter_entry.pack(side="left", fill="x", expand=True)
    filter_entry.insert(0, "")
    filter_entry.bind("<KeyRelease>", filter_products)

    # Products Treeview Table
    tree_container = tk.Frame(left_pane, bg=THEME["bg_panel"])
    tree_container.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    columns = ("col_0", "col_1", "col_2", "col_3")
    product_tree = ttk.Treeview(
        tree_container,
        columns=columns,
        show="headings",
        selectmode="browse"
    )

    product_tree.heading("col_0", text="#", command=lambda: sort_tree_column(0))
    product_tree.heading("col_1", text="Product Title", command=lambda: sort_tree_column(1, True))
    product_tree.heading("col_2", text="Price ↓", command=lambda: sort_tree_column(2, True))
    product_tree.heading("col_3", text="Rating ↓", command=lambda: sort_tree_column(3, True))

    product_tree.column("col_0", width=42, anchor="center", stretch=False)
    product_tree.column("col_1", width=220, anchor="w", stretch=True)
    product_tree.column("col_2", width=95, anchor="center", stretch=False)
    product_tree.column("col_3", width=75, anchor="center", stretch=False)

    tree_scroll = tk.Scrollbar(tree_container, orient="vertical", command=product_tree.yview)
    product_tree.configure(yscrollcommand=tree_scroll.set)

    product_tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")

    product_tree.tag_configure("evenrow", background=THEME["tree_even"])
    product_tree.tag_configure("oddrow", background=THEME["tree_odd"])
    product_tree.bind("<<TreeviewSelect>>", on_tree_select)

    # ---- RIGHT PANE: INTERACTIVE PRODUCT INSPECTOR ----
    right_pane = tk.Frame(workspace_frame, bg=THEME["bg_panel"])
    right_pane.pack(side="right", fill="both", expand=True, padx=(6, 0))

    right_header = tk.Frame(right_pane, bg=THEME["bg_panel"], padx=10, pady=8)
    right_header.pack(fill="x")

    tk.Label(
        right_header,
        text="PRODUCT INSPECTOR",
        bg=THEME["bg_panel"],
        fg=THEME["text_main"],
        font=("Segoe UI", 11, "bold")
    ).pack(side="left")

    # Details Text Area with Rich Tags
    details_box = tk.Frame(right_pane, bg=THEME["bg_subpanel"])
    details_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    details_text = tk.Text(
        details_box,
        bg=THEME["bg_subpanel"],
        fg=THEME["text_main"],
        insertbackground="white",
        font=("Segoe UI", 10),
        wrap="word",
        relief="flat",
        bd=0,
        padx=12,
        pady=12
    )
    details_scroll = tk.Scrollbar(details_box, command=details_text.yview)
    details_text.config(yscrollcommand=details_scroll.set)

    details_text.pack(side="left", fill="both", expand=True)
    details_scroll.pack(side="right", fill="y")

    # Rich Text Tag Styles
    details_text.tag_config("title", font=("Segoe UI", 12, "bold"), foreground=THEME["text_main"])
    details_text.tag_config("badge_price_lbl", font=("Segoe UI", 9, "bold"), background=THEME["bg_hover"], foreground=THEME["text_muted"])
    details_text.tag_config("badge_price_val", font=("Segoe UI", 12, "bold"), background=THEME["bg_hover"], foreground=THEME["success"])
    details_text.tag_config("badge_rating_lbl", font=("Segoe UI", 9, "bold"), background=THEME["bg_hover"], foreground=THEME["text_muted"])
    details_text.tag_config("badge_rating_val", font=("Segoe UI", 10, "bold"), background=THEME["bg_hover"], foreground=THEME["warning"])
    details_text.tag_config("section_head", font=("Segoe UI", 9, "bold"), foreground=THEME["accent_cyan"])
    details_text.tag_config("url_text", font=("Segoe UI", 9), foreground=THEME["primary_hover"], underline=1)
    details_text.tag_config("divider", foreground=THEME["border"])
    details_text.tag_config("spec_bullet", font=("Segoe UI", 9), foreground=THEME["text_main"], spacing1=4)
    details_text.tag_config("body_text", font=("Segoe UI", 9), foreground=THEME["text_muted"])
    details_text.tag_config("muted", font=("Segoe UI", 9), foreground=THEME["text_dim"])
    details_text.tag_config("placeholder", font=("Segoe UI", 11), foreground=THEME["text_dim"])
    details_text.tag_config("warning", font=("Segoe UI", 10, "bold"), foreground=THEME["warning"])

    # Make URL inside details text directly clickable!
    def on_link_click(event):
        if current_selected_product and current_selected_product.get("url"):
            webbrowser.open(current_selected_product["url"])

    details_text.tag_bind("link", "<Button-1>", on_link_click)
    details_text.tag_bind("link", "<Enter>", lambda e: details_text.config(cursor="hand2"))
    details_text.tag_bind("link", "<Leave>", lambda e: details_text.config(cursor=""))

    # Bottom Actions Bar in Right Pane
    actions_bar = tk.Frame(right_pane, bg=THEME["bg_panel"], padx=10, pady=8)
    actions_bar.pack(fill="x")

    btn_open_browser = make_hover_button(
        actions_bar,
        text="🌐 OPEN IN BROWSER",
        command=open_selected_in_browser,
        bg=THEME["primary"],
        hover_bg=THEME["primary_hover"],
        font=("Segoe UI", 9, "bold"),
        padx=14,
        pady=6
    )
    btn_open_browser.pack(side="left", padx=(0, 6))

    btn_copy_url = make_hover_button(
        actions_bar,
        text="🔗 Copy Link",
        command=copy_product_url,
        bg=THEME["bg_subpanel"],
        hover_bg=THEME["bg_hover"],
        font=("Segoe UI", 9),
        padx=12,
        pady=6
    )
    btn_copy_url.pack(side="left", padx=4)

    btn_copy_details = make_hover_button(
        actions_bar,
        text="📋 Copy Details",
        command=copy_product_details,
        bg=THEME["bg_subpanel"],
        hover_bg=THEME["bg_hover"],
        font=("Segoe UI", 9),
        padx=12,
        pady=6
    )
    btn_copy_details.pack(side="left", padx=4)

    # Initial view state
    show_empty_details()
    update_status("Ready. Enter target URL or pick a store preset.", state="normal")
    root.protocol("WM_DELETE_WINDOW", close_application)


def main():
    build_gui()
    root.after(300, bring_gui_to_front)
    root.mainloop()
