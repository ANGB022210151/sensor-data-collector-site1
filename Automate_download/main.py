"""
Automated download script for Datacake dashboard CSV exports.
Downloads sensor data from: https://app.datacake.de/pd/ea4da4f6-a3aa-4353-bb62-60c650165c36

Supports:
- Local execution
- Azure Container Instance with blob upload
"""

import os
import time
import glob
import re
import sys
import subprocess
import argparse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Azure Blob Storage imports (optional)
try:
    from azure.storage.blob import BlobServiceClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

# Configuration
DASHBOARD_URL = "https://app.datacake.de/pd/ea4da4f6-a3aa-4353-bb62-60c650165c36"
DOWNLOAD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # followtime directory
WAIT_TIME = 10  # seconds to wait for elements


def setup_driver(headless=False):
    """Setup Chrome driver with download preferences."""
    chrome_options = Options()
    
    # Set download directory
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    # Headless mode for cloud/container execution
    if headless:
        chrome_options.add_argument("--headless=new")
    
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource issues in containers
    
    # Auto-install ChromeDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver


def wait_for_download(download_dir, timeout=30):
    """Wait for download to complete (no .crdownload files)."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Check for incomplete downloads
        crdownload_files = glob.glob(os.path.join(download_dir, "*.crdownload"))
        if not crdownload_files:
            time.sleep(1)  # Extra wait to ensure file is fully written
            return True
        time.sleep(0.5)
    return False


def cleanup_duplicate_files(download_dir):
    """
    Replace original files with newly downloaded duplicates.
    Chrome adds (1), (2), etc. to filenames when files already exist.
    This function removes the original and renames the duplicate.
    """
    # Find all CSV files with (number) pattern
    pattern = re.compile(r'^(.+?)\s*\((\d+)\)(\.csv)$', re.IGNORECASE)
    
    for filename in os.listdir(download_dir):
        match = pattern.match(filename)
        if match:
            base_name = match.group(1)
            extension = match.group(3)
            original_name = base_name + extension
            
            duplicate_path = os.path.join(download_dir, filename)
            original_path = os.path.join(download_dir, original_name)
            
            # Remove original if it exists
            if os.path.exists(original_path):
                os.remove(original_path)
                print(f"  Removed old: {original_name}")
            
            # Rename duplicate to original name
            os.rename(duplicate_path, original_path)
            print(f"  Renamed: {filename} -> {original_name}")


def click_download_csv_in_modal(driver):
    """Click the 'Download CSV' button in the export modal."""
    try:
        # Wait for modal to appear - look for "Export current view" text
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Export current view')]"))
        )
        time.sleep(0.5)
        
        # Find and click the "Download CSV" button
        download_btn_selectors = [
            "//button[contains(text(), 'Download CSV')]",
            "//button[contains(., 'Download CSV')]",
            "//button[contains(@class, 'primary') and contains(text(), 'Download')]",
            "//*[contains(text(), 'Download CSV')]/ancestor::button",
            "//button[contains(@class, 'btn') and contains(., 'Download')]",
        ]
        
        for selector in download_btn_selectors:
            try:
                download_btn = driver.find_element(By.XPATH, selector)
                if download_btn.is_displayed():
                    download_btn.click()
                    return True
            except Exception:
                continue
        
        # Fallback: find any button in modal with "Download" text
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            try:
                if "Download" in btn.text and "CSV" in btn.text and btn.is_displayed():
                    btn.click()
                    return True
            except Exception:
                continue
                
        return False
        
    except Exception as e:
        return False


def close_modal_if_open(driver):
    """Close any open modal by clicking Cancel or pressing Escape."""
    try:
        from selenium.webdriver.common.keys import Keys
        
        # Try clicking Cancel button
        cancel_btns = driver.find_elements(By.XPATH, "//button[contains(text(), 'Cancel')]")
        for btn in cancel_btns:
            if btn.is_displayed():
                btn.click()
                time.sleep(0.5)
                return
        
        # Try clicking X button
        close_btns = driver.find_elements(By.CSS_SELECTOR, "[class*='close'], [aria-label='Close']")
        for btn in close_btns:
            if btn.is_displayed():
                btn.click()
                time.sleep(0.5)
                return
                
        # Press Escape key
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.5)
        
    except Exception:
        pass


def download_all_charts(driver):
    """Find and click all download buttons on the dashboard."""
    print(f"Navigating to: {DASHBOARD_URL}")
    driver.get(DASHBOARD_URL)
    
    # Wait for page to load
    time.sleep(5)
    
    # Wait for the dashboard to fully render
    try:
        WebDriverWait(driver, WAIT_TIME).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "svg, canvas, [class*='chart']"))
        )
    except Exception as e:
        print(f"Warning: Could not detect charts, continuing anyway...")
    
    # Additional wait for dynamic content
    time.sleep(3)
    
    downloaded_count = 0
    
    # Find all buttons with SVG icons - these are likely the download buttons
    # Look for buttons containing SVG elements
    all_buttons = driver.find_elements(By.XPATH, "//button[.//*[local-name()='svg']]")
    
    # Filter to unique visible buttons
    visible_buttons = []
    seen_locations = set()
    
    for btn in all_buttons:
        try:
            if btn.is_displayed():
                loc = btn.location
                size = btn.size
                # Create a key based on position
                loc_key = (loc['x'] // 10, loc['y'] // 10)  # Group nearby buttons
                if loc_key not in seen_locations:
                    seen_locations.add(loc_key)
                    visible_buttons.append(btn)
        except Exception:
            continue
    
    print(f"Found {len(visible_buttons)} buttons with SVG icons")
    
    # Try each button to see if it triggers the export modal
    for i, btn in enumerate(visible_buttons):
        try:
            # Scroll to the button
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
            time.sleep(0.3)
            
            # Check if button is still visible after scroll
            if not btn.is_displayed():
                continue
            
            # Click the button
            try:
                btn.click()
            except Exception:
                # Try JavaScript click if regular click fails
                driver.execute_script("arguments[0].click();", btn)
            
            time.sleep(1)
            
            # Check if modal appeared and click "Download CSV"
            if click_download_csv_in_modal(driver):
                downloaded_count += 1
                print(f"Downloaded file {downloaded_count}")
                wait_for_download(DOWNLOAD_DIR)
                time.sleep(2)
            else:
                # Close any open modal/dropdown
                close_modal_if_open(driver)
                
        except Exception as e:
            close_modal_if_open(driver)
            continue
    
    return downloaded_count


def upload_to_azure_blob(file_path, blob_name=None):
    """Upload a file to Azure Blob Storage."""
    if not AZURE_AVAILABLE:
        print("⚠️ Azure SDK not installed. Skipping blob upload.")
        return False
    
    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("BLOB_CONTAINER_NAME", "sensor-data")
    
    if not connection_string:
        print("⚠️ AZURE_STORAGE_CONNECTION_STRING not set. Skipping blob upload.")
        return False
    
    try:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        
        # Create container if it doesn't exist
        container_client = blob_service_client.get_container_client(container_name)
        try:
            container_client.create_container()
            print(f"📦 Created blob container: {container_name}")
        except Exception:
            pass  # Container already exists
        
        # Generate blob name with timestamp if not provided
        if blob_name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            blob_name = f"{timestamp}/{os.path.basename(file_path)}"
        
        # Upload file
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        
        with open(file_path, "rb") as data:
            blob_client.upload_blob(data, overwrite=True)
        
        print(f"☁️ Uploaded to blob: {container_name}/{blob_name}")
        return True
        
    except Exception as e:
        print(f"❌ Blob upload failed: {e}")
        return False


def upload_directory_to_blob(directory, prefix=""):
    """Upload all CSV files from a directory to Azure Blob Storage."""
    if not AZURE_AVAILABLE:
        return
    
    for filename in os.listdir(directory):
        if filename.endswith(".csv"):
            file_path = os.path.join(directory, filename)
            blob_name = f"{prefix}/{filename}" if prefix else filename
            upload_to_azure_blob(file_path, blob_name)


def main():
    """Main function to run the download automation."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Datacake CSV Download Automation")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode")
    parser.add_argument("--upload-to-blob", action="store_true", help="Upload results to Azure Blob Storage")
    args = parser.parse_args()
    
    print("=" * 50)
    print("Datacake CSV Download Automation")
    print("=" * 50)
    print(f"Download directory: {DOWNLOAD_DIR}")
    print(f"Headless mode: {args.headless}")
    print(f"Upload to blob: {args.upload_to_blob}")
    print()
    
    # Get existing files before download
    existing_files = set(os.listdir(DOWNLOAD_DIR))
    
    driver = None
    try:
        driver = setup_driver(headless=args.headless)
        count = download_all_charts(driver)
        print(f"\nAttempted {count} downloads")
        
        # Check for new files
        time.sleep(3)
        new_files = set(os.listdir(DOWNLOAD_DIR)) - existing_files
        if new_files:
            print(f"\nNew files downloaded:")
            for f in new_files:
                print(f"  - {f}")
            
            # Clean up duplicate files - replace originals with new downloads
            print(f"\nCleaning up duplicate files...")
            cleanup_duplicate_files(DOWNLOAD_DIR)
        else:
            print("\nNo new files detected. The download buttons may require manual interaction.")
            print("Try running the script without headless mode to see the browser.")

        # Run merge.py using relative paths, output in DOWNLOAD_DIR
        print("\nRunning merge.py to update merged_sensor_data.csv in output/...")
        merge_candidates = [
            os.path.join(DOWNLOAD_DIR, "Automate_download", "merge.py"),
            os.path.join(DOWNLOAD_DIR, "merge.py"),
            os.path.abspath(os.path.join(DOWNLOAD_DIR, "..", "..", "merge_algorithm", "merge.py")),
        ]
        merge_script = next((p for p in merge_candidates if os.path.exists(p)), None)
        if merge_script:
            try:
                output_dir = os.path.join(DOWNLOAD_DIR, "output")
                os.makedirs(output_dir, exist_ok=True)
                subprocess.run(
                    [
                        sys.executable,
                        merge_script,
                        "--input",
                        DOWNLOAD_DIR,
                        "--output",
                        output_dir,
                        "--sort",
                        "datetime",
                        "--order",
                        "asc",
                    ],
                    cwd=DOWNLOAD_DIR,
                    check=True,
                )
                print("Merge completed; output written to output/.")
            except subprocess.CalledProcessError as e:
                print(f"Merge script failed: {e}")
        else:
            print("merge.py not found in expected locations; skipped merging.")

        # After producing output/merged_sensor_data.csv, append it into Combined
        print("\nRunning final_merge.py to append into Combined and sort time ascending...")
        final_merge_candidates = [
            os.path.join(DOWNLOAD_DIR, "Automate_download", "final_merge.py"),
            os.path.join(DOWNLOAD_DIR, "final_merge.py"),
        ]
        final_merge_script = next((p for p in final_merge_candidates if os.path.exists(p)), None)
        if final_merge_script:
            try:
                output_dir = os.path.join(DOWNLOAD_DIR, "output")
                combined_dir = os.path.join(DOWNLOAD_DIR, "Combined")
                os.makedirs(combined_dir, exist_ok=True)
                subprocess.run(
                    [
                        sys.executable,
                        final_merge_script,
                        "--input",
                        output_dir,
                        "--combined",
                        combined_dir,
                        "--dataset-file",
                        "merged_sensor_data.csv",
                        "--outfile",
                        "merged_sensor_data.csv",
                    ],
                    cwd=DOWNLOAD_DIR,
                    check=True,
                )
                print("Final merge completed; Combined CSV updated and time sorted.")
            except subprocess.CalledProcessError as e:
                print(f"Final merge script failed: {e}")
        else:
            print("final_merge.py not found in expected locations; skipped final combine step.")
        
        # Upload to Azure Blob Storage if enabled
        if args.upload_to_blob:
            print("\n" + "=" * 50)
            print("Uploading to Azure Blob Storage...")
            print("=" * 50)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Upload the merged output file
            output_file = os.path.join(DOWNLOAD_DIR, "output", "merged_sensor_data.csv")
            if os.path.exists(output_file):
                upload_to_azure_blob(output_file, f"daily/{timestamp}/merged_sensor_data.csv")
            
            # Upload the combined file
            combined_file = os.path.join(DOWNLOAD_DIR, "Combined", "merged_sensor_data.csv")
            if os.path.exists(combined_file):
                upload_to_azure_blob(combined_file, "combined/merged_sensor_data.csv")
            
            # Upload raw CSV files
            print("\nUploading raw sensor files...")
            for filename in os.listdir(DOWNLOAD_DIR):
                if filename.endswith(".csv") and filename not in ["merged_sensor_data.csv"]:
                    file_path = os.path.join(DOWNLOAD_DIR, filename)
                    upload_to_azure_blob(file_path, f"daily/{timestamp}/raw/{filename}")
            
    except Exception as e:
        print(f"Error: {e}")
        raise
    finally:
        if driver:
            print("\nClosing browser...")
            driver.quit()
    
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
