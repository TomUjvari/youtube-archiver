# Youtube Archiver  
This project allows you to archive an entire Youtube channel's content with their upload date embedded in the saved videos. Also works for playlists and single videos.  

## Requirements  
- Get your own [Youtube API key](https://console.cloud.google.com/apis/api/youtube.googleapis.com).  
- [yt-dlp](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.02.04): on Windows, download the exe and put in the same folder as main.py. On Linux, simply install the package.  
- [Python](https://www.python.org/) with the `requests` library installed.  
- [FFMPEG](https://ffmpeg.org/) for encoding to MP4 if you want to.  

> [!NOTE]
> You might get flagged as a bot. It is highly recommended to install the `yt-dlp-ejs` python library and a [supported javascript runtime](https://github.com/yt-dlp/yt-dlp/wiki/EJS) in order to avoid detection. The program will ask you for the browser to get cookies from (firefox/chrome) as well as your Javascript runtime (deno/node/bun/quickjs).
