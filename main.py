import json
import requests
import subprocess
import time
import os
from datetime import datetime
import sys
from urllib.parse import urlparse, parse_qs
import platform

# Platform detection
IS_WINDOWS = os.name == 'nt' or platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'

# Import Windows-specific modules only on Windows
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

BASE_URL = "https://www.googleapis.com/youtube/v3"

#region Settings

def change_settings():
    api_key = input("API key: ")
    browser = input("Preferred browser (firefox/chrome): ")
    js_runtime = input("JS runtime (deno/node/bun/quickjs): ")
    _formatInput = input("Save as MP4 instead of MKV? (Y/n): ")
    format = "mkv" if _formatInput.strip().lower() == "n" else "mp4"

    result = {"API_KEY": api_key, "BROWSER": browser, "JS_RUNTIME": js_runtime, "FORMAT": format}

    with open("settings.json", "w") as fp:
        json.dump(result, fp, indent=4)
        print("Settings successfully saved to settings.json!")

    return result

def get_settings():
    try:
        with open("settings.json", "r") as json_file:
            data = json.load(json_file)
            return data
    except (json.JSONDecodeError, FileNotFoundError):
        print("Settings not found. Let's set them.")
        return change_settings()

#endregion

#region Youtube API

def get_channel_id(api_key, handle):
    # Remove @ if present to prevent double encoding issues if user adds it
    handle = handle.replace("@", "")
    param = f"forHandle={handle}"
    url = f"{BASE_URL}/channels?key={api_key}&part=id,contentDetails&{param}"
    response = requests.get(url)
    data = response.json()

    if "items" not in data or len(data["items"]) == 0:
        print(f"Error: Could not find channel for '{handle}'.")
        # Print debug info safely
        if "error" in data:
            print("API Error:", data["error"]["message"])
        sys.exit(1)

    return data["items"][0]["id"]


def get_list_of_video_links(api_key:str, channel_id:str, output_file:str = None):
    url = f"{BASE_URL}/channels?key={api_key}&part=contentDetails&id={channel_id}"
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
            f"{BASE_URL}/playlistItems"
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
        f"{BASE_URL}/videos"
        f"?part=snippet&id={video_id}&key={api_key}"
    )
    data = requests.get(url).json()

    if not data.get("items"):
        raise RuntimeError("Could not retrieve video metadata")

    published_at = data["items"][0]["snippet"]["publishedAt"]
    return datetime.fromisoformat(published_at.replace("Z", "+00:00"))


def get_playlist_videos(api_key: str, playlist_url: str):
    """
    Fetch all videos from a playlist URL and save them to:
    ./saved/playlist_{ID}/video_list.txt
    
    Returns:
        List of (publish_date, video_url) and the folder path
    """

    # --- Extract playlist ID ---
    parsed = urlparse(playlist_url)
    query = parse_qs(parsed.query)

    if "list" not in query:
        # Fallback if the user pasted just the ID or a different format
        if "list=" in playlist_url:
             playlist_id = playlist_url.split("list=")[1].split("&")[0]
        else:
            raise ValueError("Invalid playlist URL: missing list parameter")
    else:
        playlist_id = query["list"][0]

    # --- Prepare output directory ---
    base_dir = os.path.join("saved", f"playlist_{playlist_id}")
    os.makedirs(base_dir, exist_ok=True)

    output_file = os.path.join(base_dir, "video_list.txt")

    videos = []
    page_token = ""

    print(f"Fetching playlist videos for ID: {playlist_id}...")

    while True:
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
            "pageToken": page_token,
            "key": api_key,
        }

        res = requests.get(f"{BASE_URL}/playlistItems", params=params).json()
        
        if "error" in res:
            print("API Error:", res["error"]["message"])
            break

        for item in res.get("items", []):
            snippet = item.get("snippet")
            if not snippet:
                continue

            video_id = snippet["resourceId"]["videoId"]
            publish_date = snippet["publishedAt"]
            videos.append((publish_date, f"https://youtu.be/{video_id}"))

        page_token = res.get("nextPageToken", "")
        if not page_token:
            break

    # Sort oldest → newest
    videos.sort(key=lambda x: x[0])

    # --- Save to file ---
    with open(output_file, "w", encoding="utf-8") as f:
        for date, link in videos:
            f.write(f"{date} {link}\n")

    print(f"Saved {len(videos)} videos to {output_file}")

    return videos, base_dir

#endregion

#region Video Saving

def set_windows_file_times(path, dt):
    """
    Set creation, access, and modification times on Windows.
    dt must be a timezone-aware UTC datetime.
    """
    if not IS_WINDOWS:
        return
    
    FILE_WRITE_ATTRIBUTES = 0x100
    OPEN_EXISTING = 3

    # Ensure path is absolute for ctypes
    path = os.path.abspath(path)

    try:
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
    except Exception:
        pass # Fail silently on timestamp errors to keep process running


def save_list_of_videos_from_list(links:list, format:str, output_dir:str, cookies_browser:str, js_runtime:str):
    for i, (date, url) in enumerate(links):
        print(f"[{i+1}/{len(links)}] Processing {url}...")
        try:
            dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
            save_video(url, dt, format, output_dir, cookies_browser, js_runtime)
        except Exception as e:
            print(f"Failed to process {url}: {e}")


def save_list_of_videos_from_txt_file(handle:str, format:str, cookies_browser:str, js_runtime:str):
    # Reconstruct the expected file path
    base_dir = os.path.join("saved", handle)
    video_list_path = os.path.join(base_dir, "video_list.txt")

    if not os.path.exists(video_list_path):
        print(f"Error: No such file: {video_list_path}")
        print("Run option [1] first to generate the video list.")
        return

    with open(video_list_path, "r", encoding="utf-8") as f:
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


def get_ytdlp_command():
    """Get the appropriate yt-dlp command based on the platform."""
    if IS_WINDOWS:
        return ".\\yt-dlp.exe"
    else:
        return "yt-dlp"


def save_video(url:str, date:datetime, format:str, output_dir:str, cookies_browser:str, js_runtime:str):
    # Snapshot files in the specific output directory
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    before_files = set(os.listdir(output_dir))

    # Construct the output path template for yt-dlp
    output_template = os.path.join(output_dir, "%(title)s.%(ext)s")
    
    cmd = [get_ytdlp_command()]
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
        result = subprocess.run(cmd, capture_output=False) 
        if result.returncode == 0:
            break
        print("Download failed, retrying in 5 seconds...")
        time.sleep(5)
        retry_count += 1
    
    if retry_count == 3:
        print(f"Error: yt-dlp failed to download {url} after 3 retries.")
        return 

    # Check for new files in the output directory
    after_files = set(os.listdir(output_dir))
    new_files = list(after_files - before_files)

    video_path = None
    
    # 1. Look for exact format match among new files
    for f in new_files:
        if f.lower().endswith(f".{format}"):
            video_path = os.path.join(output_dir, f)
            break
            
    # 2. Fallback: take the largest new file
    if not video_path and new_files:
        new_files_full_path = [os.path.join(output_dir, f) for f in new_files]
        new_files_full_path.sort(key=os.path.getsize, reverse=True)
        video_path = new_files_full_path[0]

    if not video_path:
        # This usually means the file already existed and yt-dlp skipped it.
        # We return quietly so we don't try to set timestamps on a null path.
        print(f"No new file created (File likely already exists).")
        return

    # Set modification & access time (portable)
    ts = date.timestamp()
    try:
        os.utime(video_path, (ts, ts))
        # Set creation time (Windows only)
        if IS_WINDOWS:
            set_windows_file_times(video_path, date)
    except OSError as e:
        print(f"Could not set timestamps on {video_path}: {e}")

#endregion

#region Main Commands

def get_main_input():
    cmd = input(
        "\nWhat do you want to do?"
        "\n[1] Download an entire channel"
        "\n[2] Resume channel download (from saved list)"
        "\n[3] Download a single video"
        "\n[4] Download a Playlist"
        "\n[5] Update yt-dlp"
        "\n[6] Change settings"
        "\n[7] Quit"
        "\n>"
    )
    if cmd not in ["1", "2", "3", "4", "5", "6", "7"]:
        print("Invalid input. Try again.")
        return get_main_input()
    return cmd


def get_download_input(single_mode:bool = False):
    settings = get_settings()
    API_KEY = settings["API_KEY"]
    COOKIES = settings["BROWSER"]
    JS_RUNTIME = settings["JS_RUNTIME"]
    FORMAT = settings["FORMAT"]
    
    result = {
        "API_KEY": API_KEY,
        "FORMAT": FORMAT,
        "COOKIES": COOKIES,
        "JS_RUNTIME": JS_RUNTIME,
    }

    if single_mode:
        VIDEO_URL = input("Enter video URL: \n>").strip()
        result["VIDEO_URL"] = VIDEO_URL
    else:
        HANDLE = input("Enter channel handle (e.g. ChannelName): \n>").strip().replace("@", "")
        result["HANDLE"] = HANDLE 
    
    return result

def get_playlist_input():
    settings = get_settings()
    
    url = input("Enter Playlist URL: \n>").strip()
    
    return {
        "API_KEY": settings["API_KEY"],
        "FORMAT": settings["FORMAT"],
        "COOKIES": settings["BROWSER"],
        "JS_RUNTIME": settings["JS_RUNTIME"],
        "URL": url
    }


def download_channel(api_key:str, handle:str, format:str, cookies:str, js_runtime:str):
    # 1. Define and Create Directory Path: ./saved/{handle}
    folder_path = os.path.join("saved", handle)

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        print(f"Created directory: {folder_path}")

    # 2. Get Channel ID safely
    CHANNEL_ID = get_channel_id(api_key, handle)
    print(f"Found Channel ID: {CHANNEL_ID}")

    # 3. Get Links
    list_output_path = os.path.join(folder_path, "video_list.txt")
    VIDEO_LINKS = get_list_of_video_links(api_key, CHANNEL_ID, list_output_path)
    
    # 4. Save Videos
    save_list_of_videos_from_list(VIDEO_LINKS, format, folder_path, cookies, js_runtime)
    
    print(f"\nAll tasks completed. Videos are in: {folder_path}")


def download_channel_from_txt_file(handle:str, format:str, cookies:str, js_runtime:str):
    # 1. Define folder path just for the final print message logic
    folder_path = os.path.join("saved", handle)

    # 2. Save Videos (logic handles reading the file)
    save_list_of_videos_from_txt_file(handle, format, cookies, js_runtime)
    
    print(f"\nAll tasks completed. Videos are in: {folder_path}")


def download_playlist_process(api_key: str, playlist_url: str, format: str, cookies: str, js_runtime: str):
    # 1. Fetch videos and get the determined folder path
    video_links, folder_path = get_playlist_videos(api_key, playlist_url)
    
    # 2. Save Videos
    save_list_of_videos_from_list(video_links, format, folder_path, cookies, js_runtime)
    
    print(f"\nAll tasks completed. Videos are in: {folder_path}")


def download_single_video(api_key: str, url: str, format: str, cookies: str, js_runtime: str):
    output_dir = input("Enter output directory (default: ./saved/single):\n>").strip()

    if not output_dir:
        output_dir = os.path.join("saved", "single")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        dt = get_video_publish_date(api_key, url)
        print(f"Video publish date: {dt.isoformat()}")
    except Exception as e:
        print(f"Warning: Could not fetch date from API ({e}). Using current time.")
        dt = datetime.now()

    save_video(url, dt, format, output_dir, cookies, js_runtime)


def update_yt_dlp():
    cmd = [get_ytdlp_command(), "-U"]
    subprocess.run(cmd, capture_output=False)


def check_dependencies():
    """Check for required dependencies on the current platform."""
    missing = []
    
    # Check for yt-dlp
    ytdlp_cmd = get_ytdlp_command()
    try:
        result = subprocess.run([ytdlp_cmd, "--version"], 
                              capture_output=True, 
                              text=True,
                              timeout=5)
        if result.returncode != 0:
            missing.append("yt-dlp")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        missing.append("yt-dlp")
    
    # Check for ffmpeg (required for embedding operations)
    if IS_LINUX:
        try:
            result = subprocess.run(["ffmpeg", "-version"], 
                                  capture_output=True, 
                                  text=True,
                                  timeout=5)
            if result.returncode != 0:
                missing.append("ffmpeg")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            missing.append("ffmpeg")
    
    if missing:
        print("\n⚠️  WARNING: Missing dependencies!")
        print(f"Missing: {', '.join(missing)}\n")
        
        if IS_LINUX:
            print("On Linux, install them with:")
            if "yt-dlp" in missing:
                print("  sudo apt install yt-dlp  # or: pip install yt-dlp")
            if "ffmpeg" in missing:
                print("  sudo apt install ffmpeg")
        else:
            print("Please ensure yt-dlp.exe is in the same directory as this script.")
            print("Download from: https://github.com/yt-dlp/yt-dlp/releases")
        
        print()
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != 'y':
            sys.exit(1)

#endregion


# Main Process
if __name__ == "__main__":
    print(f"Running on: {platform.system()}")
    check_dependencies()
    
    while True:
        cmd = get_main_input()

        match cmd:
            case "1":
                _ = get_download_input()
                download_channel(_["API_KEY"], _["HANDLE"], _["FORMAT"], _["COOKIES"], _["JS_RUNTIME"])
            case "2":
                print("INFO: Resuming from saved/handle/video_list.txt")
                _ = get_download_input()
                download_channel_from_txt_file(_["HANDLE"], _["FORMAT"], _["COOKIES"], _["JS_RUNTIME"])
            case "3":
                _ = get_download_input(single_mode=True)
                download_single_video(_["API_KEY"], _["VIDEO_URL"], _["FORMAT"], _["COOKIES"], _["JS_RUNTIME"])
            case "4":
                _ = get_playlist_input()
                download_playlist_process(_["API_KEY"], _["URL"], _["FORMAT"], _["COOKIES"], _["JS_RUNTIME"])
            case "5":
                update_yt_dlp()
            case "6":
                change_settings()
            case "7":
                print("Exiting...")
                break

        print("\n----- TASK COMPLETED -----\n")