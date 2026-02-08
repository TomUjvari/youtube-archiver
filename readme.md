# Youtube Archiver  
This project allows you to archive an entire Youtube channel's content with their upload date embedded in the saved videos.  

## Requirements  
- Get your own [Youtube API key](https://console.cloud.google.com/apis/api/youtube.googleapis.com).  
- Download [yt-dlp](https://github.com/yt-dlp/yt-dlp/releases/tag/2026.02.04) and put the exe in the folder of this project.  
- Python with the `requests` library installed.   

> [!NOTE]
> You might get flagged as a bot. It is highly recommended to install the `yt-dlp-ejs` python library and a [supported javascript runtime](https://github.com/yt-dlp/yt-dlp/wiki/EJS) in order to avoid detection. The program will ask you for the browser to get cookies from (firefox/chrome) as well as your Javascript runtime (deno/node/bun/quickjs).

For now this project only works for Windows, it will be available for Linux soon.