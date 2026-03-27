import os
import csv
import requests
import time
import threading
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===== ENV VARIABLES =====
CSV_FILE = os.getenv("CSV_FILE", "video.csv")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./videos")
LOG_FILE = os.getenv("LOG_FILE", "download.log")
FAILED_FILE = os.getenv("FAILED_FILE", "failed.csv")

MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
TIMEOUT = int(os.getenv("TIMEOUT", 30))

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

lock = threading.Lock()


# ===== LOGGING =====
def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    message = f"[{timestamp}] {msg}"

    with lock:
        print(message)
        with open(LOG_FILE, "a") as f:
            f.write(message + "\n")


# ===== DYNAMIC CONCURRENCY =====
def get_dynamic_workers():
    
    try:
        start = time.time()
        requests.get("https://www.google.com", timeout=5)
        latency = time.time() - start

        if latency < 0.2:
            workers = 10   # High bandwidth
        elif latency < 0.5:
            workers = 5    # Medium bandwidth
        else:
            workers = 2    # Low bandwidth

        log(f"Dynamic concurrency selected: {workers} workers (latency: {latency:.2f}s)")
        return workers

    except Exception:
        log("Failed to detect bandwidth. Using default workers = 3")
        return 3


# ===== FILENAME GENERATION =====
def filename(url, title=None, video_id=None):
    base = os.path.basename(urlparse(url).path)

    if title:
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip()

        if video_id:
            return f"{video_id}_{safe_title}.mp4"
        return f"{safe_title}.mp4"

    return base or f"video_{abs(hash(url))}.mp4"


# ===== DOWNLOAD FUNCTION =====
def download(row):
    try:
        video_id = row[0].strip() if len(row) > 0 else None
        title = row[1].strip() if len(row) > 1 else None
        url = row[4].strip()

        if not url.startswith("http"):
            return ("skip", url)

        file_path = os.path.join(DOWNLOAD_DIR, filename(url, title, video_id))

        # Resume support
        if os.path.exists(file_path):
            log(f"Skipping (exists): {file_path}")
            return ("success", url)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log(f"Downloading ({attempt}/{MAX_RETRIES}): {url}")

                with requests.get(url, stream=True, timeout=TIMEOUT) as r:
                    r.raise_for_status()

                    with open(file_path, "wb") as f:
                        for chunk in r.iter_content(8192):
                            if chunk:
                                f.write(chunk)

                log(f"Saved: {file_path}")
                return ("success", url)

            except requests.exceptions.RequestException as e:
                log(f"Retry {attempt} failed: {e}")
                time.sleep(2 * attempt)

        # Failed after retries
        log(f"Failed: {url}")

        with lock:
            with open(FAILED_FILE, "a") as f:
                f.write(url + "\n")

        return ("fail", url)

    except Exception as e:
        log(f"Unexpected error: {e}")
        return ("fail", "unknown")


# ===== MAIN =====
def main():
    start_time = time.time()
    success = 0
    fail = 0

    rows = []

    # Load CSV
    try:
        with open(CSV_FILE, encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)

            for row in reader:
                rows.append(row)

    except FileNotFoundError:
        log(f"CSV file not found: {CSV_FILE}")
        return

    total = len(rows)

    log(f"Starting download for {total} files...\n")

    # ===== DYNAMIC THREAD COUNT =====
    max_workers = get_dynamic_workers()

    # ===== PARALLEL EXECUTION =====
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(download, row) for row in rows]

        for i, future in enumerate(as_completed(futures), 1):
            status, _ = future.result()

            if status == "success":
                success += 1
            elif status == "fail":
                fail += 1

            # Progress tracking
            elapsed = time.time() - start_time
            avg_time = elapsed / i
            remaining = avg_time * (total - i)

            log(f"Progress: {i}/{total} | Success: {success} | Fail: {fail}")
            log(f"ETA: {int(remaining)} sec\n")

    log("===== DONE =====")
    log(f"Total: {total}, Downloaded: {success}, Failed: {fail}")


if __name__ == "__main__":
    main()
