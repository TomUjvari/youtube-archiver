import json
import requests
import subprocess
import time
import os
from datetime import datetime
import ctypes
from ctypes import wintypes
import sys

#region Youtube API

def get_api_key():
    new_key = None

    try:
        with open("settings.json", "r") as json_file:
            data = json.load(json_file)
    except (json.JSONDecodeError, FileNotFoundError):
        data = {"API_KEY": ""}

    if data.get("API_KEY", "") == "":
        new_key = input("No API key found.\nEnter your own (leave empty to quit): ")
        if new_key == "":
            quit()

        with open("settings.json", "w") as fp:
            json.dump({"API_KEY": new_key}, fp, indent=4)
            print("API key successfully saved to settings.json!")

        return new_key

    return data["API_KEY"]


def get_channel_id(api_key, handle):
    # Sanitize handle
    handle = handle.strip()
    
    # Choose the correct parameter based on input format
    if handle.startswith("@"):
        param = f"forHandle={handle}"
    else:
        # Fallback for legacy usernames, though modern usage usually prefers handles
        param = f"forUsername={handle}"

    url = f"https://www.googleapis.com/youtube/v3/channels?key={api_key}&part=id,contentDetails&{param}"
    response = requests.get(url)
    data = response.json()

    if "items" not in data or len(data["items"]) == 0:
        print(f"Error: Could not find channel for '{handle}'.")
        print("Debug response:", data)
        sys.exit(1)

    return data["items"][0]["id"]


def get_list_of_video_links(api_key:str, channel_id:str, output_file:str = None):
    url = f"https://www.googleapis.com/youtube/v3/channels?key={api_key}&part=contentDetails&id={channel_id}"
    data = requests.get(url).json()
    
    try:
        uploads_id = data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except (IndexError, KeyError):
        print("Error: Could not retrieve uploads playlist. Check API Key or Channel ID.")
        sys.exit(1)

    videos = []
    page_token = ""
    print("Fetching video list...")

    while True:
        url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems"
            f"?part=snippet&playlistId={uploads_id}"
            f"&maxResults=50&pageToken={page_token}&key={api_key}"
        )
        res = requests.get(url).json()
        for item in res.get("items", []):
            video_id = item["snippet"]["resourceId"]["videoId"]
            publish_date = item["snippet"]["publishedAt"]
            videos.append((publish_date, f"https://youtu.be/{video_id}"))

        page_token = res.get("nextPageToken", "")
        if not page_token:
            break

    # Sort by date (oldest first)
    videos.sort(key=lambda x: x[0], reverse=False)

    if output_file:
        with open(output_file, "w") as f:
            for date, link in videos:
                f.write(f"{date} {link}\n")
        print(f"Saved {len(videos)} videos to {output_file}")

    return videos


def get_video_publish_date(api_key: str, video_url: str) -> datetime:
    # Extract video ID
    if "v=" in video_url:
        video_id = video_url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in video_url:
        video_id = video_url.split("youtu.be/")[1].split("?")[0]
    else:
        raise ValueError("Invalid YouTube URL")

    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet&id={video_id}&key={api_key}"
    )
    data = requests.get(url).json()

    if not data.get("items"):
        raise RuntimeError("Could not retrieve video metadata")

    published_at = data["items"][0]["snippet"]["publishedAt"]
    return datetime.fromisoformat(published_at.replace("Z", "+00:00"))


#endregion

#region Video Saving

def set_windows_file_times(path, dt):
    """
    Set creation, access, and modification times on Windows.
    dt must be a timezone-aware UTC datetime.
    """
    FILE_WRITE_ATTRIBUTES = 0x100
    OPEN_EXISTING = 3

    # Ensure path is absolute for ctypes
    path = os.path.abspath(path)

    handle = ctypes.windll.kernel32.CreateFileW(
        path,
        FILE_WRITE_ATTRIBUTES,
        0,
        None,
        OPEN_EXISTING,
        0,
        None
    )

    if handle == -1:
        # Identifying the error can be helpful, but we pass to avoid crashing the whole script
        print(f"Warning: Failed to open file handle for timestamp update: {path}")
        return

    # Convert datetime to Windows FILETIME
    windows_epoch = datetime(1601, 1, 1, tzinfo=dt.tzinfo)
    intervals = int((dt - windows_epoch).total_seconds() * 10**7)

    low = intervals & 0xFFFFFFFF
    high = intervals >> 32

    filetime = wintypes.FILETIME(low, high)

    ctypes.windll.kernel32.SetFileTime(
        handle,
        ctypes.byref(filetime),
        ctypes.byref(filetime),
        ctypes.byref(filetime)
    )

    ctypes.windll.kernel32.CloseHandle(handle)


def save_list_of_videos_from_list(links:list, format:str, output_dir:str, cookies_browser:str, js_runtime:str):
    total = len(links)
    for i, line in enumerate(links):
        date_str, url = line[0], line[1]
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        
        print(f"[{i+1}/{total}] Processing {url}...")
        try:
            save_video(url, dt, format, output_dir, cookies_browser, js_runtime)
        except Exception as e:
            print(f"Failed to process {url}: {e}")


def save_list_of_videos_from_txt_file(handle: str, format: str, cookies_browser: str, js_runtime: str):
    """
    Reads ./saved/{handle}/video_list.txt and saves all listed videos.
    """
    base_dir = os.path.join("saved", handle)
    txt_path = os.path.join(base_dir, "video_list.txt")

    if not os.path.exists(txt_path):
        raise FileNotFoundError(f"Video list not found: {txt_path}")

    with open(txt_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    total = len(lines)
    for i, line in enumerate(lines):
        try:
            date_str, url = line.split(maxsplit=1)
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            print(f"Skipping invalid line: {line}")
            continue

        print(f"[{i+1}/{total}] Processing {url}...")
        try:
            save_video(url, dt, format, base_dir, cookies_browser, js_runtime)
        except Exception as e:
            print(f"Failed to process {url}: {e}")



def save_video(url:str, date:datetime, format:str, output_dir:str, cookies_browser:str, js_runtime:str):
    # Snapshot files in the specific output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    before_files = set(os.listdir(output_dir))

    # Construct the output path template for yt-dlp
    # This automatically saves it into the correct folder
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
    
    cmd = [".\\yt-dlp.exe"]
    if cookies_browser:
        cmd.extend(["--cookies-from-browser", cookies_browser])
    if js_runtime:
        cmd.extend(["--js-runtimes", js_runtime])
    cmd.extend([
        "--embed-subs",
        "--embed-thumbnail",
        "--embed-metadata",
        "--embed-chapters",
        "--embed-info-json",
        "--remux-video", format,
        "-o", output_template,
        url
    ])

    # Run yt-dlp
    retry_count = 0
    while retry_count < 3:
        result = subprocess.run(cmd, capture_output=False) # capture_output=False allows you to see yt-dlp progress
        if result.returncode == 0:
            break
        print("Download failed, retrying in 5 seconds...")
        time.sleep(5)
        retry_count += 1
    
    if retry_count == 3:
        raise RuntimeError("yt-dlp failed after 3 retries.")

    # Check for new files in the output directory
    after_files = set(os.listdir(output_dir))
    new_files = list(after_files - before_files)

    # Filter for likely video/metadata files to find the main video file
    # We look for the file ending with the requested format
    video_path = None
    
    # First pass: look for exact format match
    for f in new_files:
        if f.lower().endswith(f".{format}"):
            video_path = os.path.join(output_dir, f)
            break
            
    # Fallback: if remuxing failed or behavior changed, take the largest new file
    if not video_path and new_files:
        # Sort new files by size, largest first, assuming video is largest
        new_files_full_path = [os.path.join(output_dir, f) for f in new_files]
        new_files_full_path.sort(key=os.path.getsize, reverse=True)
        video_path = new_files_full_path[0]

    if not video_path:
        # If the file already existed, yt-dlp might not have created a "new" file.
        # We can try to guess the filename, but for now we raise error or just skip.
        print(f"Warning: No new file detected for {url} (File might already exist).")
        return

    # Set modification & access time (portable)
    ts = date.timestamp()
    try:
        os.utime(video_path, (ts, ts))
        # Set creation time (Windows only)
        set_windows_file_times(video_path, date)
    except OSError as e:
        print(f"Could not set timestamps on {video_path}: {e}")

#endregion

#region Main Commands

def get_main_input():
    cmd = input(
        "What do you want to do?"
        "\n[1] Download an entire channel"
        "\n[2] Download an entire channel from the video list file (backup option)"
        "\n[3] Download a single video by URL"
        "\n[4] Update yt-dlp"
        "\n[5] Quit"
        "\n>"
    )
    if cmd not in ["1", "2", "3", "4", "5"]:
        print("Invalid input. Try again.")
        return get_main_input()
    return cmd



def get_download_input(single_mode:bool = False):
    API_KEY = get_api_key()

    if single_mode:
        VIDEO_URL = input("Enter video URL: \n>").strip()
    else:
        HANDLE = input("Enter channel handle (e.g. @ChannelName): \n>")
    
    _formatInput = input("Do you want to save the videos as MP4 instead of MKV? (Y/n) \n>")
    FORMAT = "mkv" if _formatInput.strip().lower() == "n" else "mp4"

    COOKIES = None
    JS_RUNTIME = None

    # Cookies
    _cookies_input = input("Do you want to use cookies from your browser? (input the name of your browser): \n>")
    if _cookies_input.lower() in ["firefox", "chrome", "safari"]:
        COOKIES = _cookies_input.lower()

        # JS Runtime
        _js_runtime = input("Do you want to use a JS runtime from your browser? (input the name of your browser): \n>")
        if _js_runtime.lower() in ["deno", "node", "bun", "quickjs"]:
            JS_RUNTIME = _js_runtime.lower()
        else:
            print("JS runtime name not recognized. It won't be used this time.")

    else:
        print("Browser name not recognized. Cookies won't be used this time.")
    
    result = {
        "API_KEY": API_KEY,
        "FORMAT": FORMAT,
        "COOKIES": COOKIES,
        "JS_RUNTIME": JS_RUNTIME,
    }
    if single_mode:
        result["VIDEO_URL"] = VIDEO_URL
    else:
        result["HANDLE"] = HANDLE,
    
    return  result


def download_channel(api_key:str, handle:str, format:str, cookies:str, js_runtime:str):
    # 1. Define and Create Directory Path: ./saved/{handle}
    clean_handle = handle.replace("@", "").strip()
    # Path is now ./saved/handle_name
    folder_path = os.path.join("saved", clean_handle)

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"Created directory: {folder_path}")

    # 2. Get Channel ID safely
    CHANNEL_ID = get_channel_id(api_key, handle)
    print(f"Found Channel ID: {CHANNEL_ID}")

    # 3. Get Links
    # Save the list inside the specific handle folder
    list_output_path = os.path.join(folder_path, "video_list.txt")
    VIDEO_LINKS = get_list_of_video_links(api_key, CHANNEL_ID, list_output_path)
    
    # 4. Save Videos to the new path
    save_list_of_videos_from_list(VIDEO_LINKS, format, folder_path, cookies, js_runtime)
    
    print(f"\nAll tasks completed. Videos are in: {folder_path}")


def download_channel_from_txt_file(api_key:str, handle:str, format:str, cookies:str, js_runtime:str):
    # 1. Define and Create Directory Path: ./saved/{handle}
    clean_handle = handle.replace("@", "").strip()
    # Path is now ./saved/handle_name
    folder_path = os.path.join("saved", clean_handle)

    # 2. Get Channel ID safely
    CHANNEL_ID = get_channel_id(api_key, handle)
    print(f"Found Channel ID: {CHANNEL_ID}")
    
    # 4. Save Videos
    save_list_of_videos_from_txt_file(clean_handle, format, cookies, js_runtime)
    
    print(f"\nAll tasks completed. Videos are in: {folder_path}")


def download_single_video(api_key: str, url: str, format: str, cookies: str, js_runtime: str):
    output_dir = input("Enter output directory (default: ./saved/single):\n>").strip()

    if not output_dir:
        output_dir = os.path.join("saved", "single")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    dt = get_video_publish_date(api_key, url)
    print(f"Video publish date: {dt.isoformat()}")

    save_video(url, dt, format, output_dir, cookies, js_runtime)


def update_yt_dlp():
    cmd = [
        ".\\yt-dlp.exe",
        "-U"
    ]
    subprocess.run(cmd, capture_output=False)

#endregion

# Main Process
if __name__ == "__main__":
    while True:
        cmd = get_main_input()

        match cmd:
            case "1":
                _ = get_download_input()
                download_channel(_["API_KEY"], _["HANDLE"], _["FORMAT"], _["COOKIES"], _["JS_RUNTIME"])
            case "2":
                print("INFO: This option is meant to be used as a way to resume where the previous attempted failed.")
                _ = get_download_input()
                download_channel_from_txt_file(_["API_KEY"], _["HANDLE"], _["FORMAT"], _["COOKIES"], _["JS_RUNTIME"])
            case "3":
                _ = get_download_input(single_mode=True)
                download_single_video(_["API_KEY"], _["VIDEO_URL"], _["FORMAT"], _["COOKIES"], _["JS_RUNTIME"])
            case "4":
                update_yt_dlp()
            case "5":
                quit()


        print("\n----- TASK COMPLETED -----\n")
