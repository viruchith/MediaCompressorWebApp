# Image & Video Compressor Web App

A Flask-based web application for batch compressing images and videos using ImageMagick and FFmpeg. The app provides a web interface to queue files for compression, monitor progress, and manage the compression queue.

## Features

- **Batch Compression:** Add entire folders of images/videos for compression.
- **Supported Formats:** 
  - Images: jpg, jpeg, png, gif, bmp, tiff, webp, raw formats, etc.
  - Videos: mp4, mov, avi, mkv, webm, flv, wmv, m4v, 3gp, mpeg, mpg.
- **Compression Tools:** Uses [ImageMagick](https://imagemagick.org/) for images and [FFmpeg](https://ffmpeg.org/) for videos.
- **Progress Tracking:** Real-time queue and progress updates via WebSockets.
- **Queue Management:** View, clear, and monitor compression jobs.

## Requirements

- Python 3.7+
- [Flask](https://flask.palletsprojects.com/)
- [Flask-SocketIO](https://flask-socketio.readthedocs.io/)
- [ImageMagick](https://imagemagick.org/) (`magick` command must be available)
- [FFmpeg](https://ffmpeg.org/) (`ffmpeg` command must be available)

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/image-compressor-wapp.git
   cd image-compressor-wapp
   ```

2. **Install Python dependencies:**
   ```bash
    pip install flask flask-socketio Pillow
    ```

3. **Install ImageMagick and FFmpeg:**
   - **Ubuntu/Debian:**  
     `sudo apt-get install imagemagick ffmpeg`
   - **MacOS (Homebrew):**  
     `brew install imagemagick ffmpeg`
   - **Windows:**  
     Download and install from official websites.

## Usage

1. **Start the server:**
   ```bash
   python main.py
   ```

2. **Open the web interface:**
   - Visit [http://localhost:5000](http://localhost:5000) in your browser.

3. **Add folders for compression:**
   - Use the web UI to specify input and output folders.
   - Monitor progress and queue status in real-time.

## API Endpoints

- `GET /files` — List all files in the queue.
- `GET /queue_counts` — Get queue statistics.
- `POST /folder` — Add a folder for compression.
- `POST /clear_completed` — Remove completed jobs from the queue.

## Notes

- Output files are saved in the specified output folder, preserving the input folder structure.
- Compression settings are hardcoded for simplicity (quality 75 for images, CRF 28 for videos).
- Only supported file types are queued.

## License

MIT License

## Acknowledgements

- [ImageMagick](https://imagemagick.org/)
- [FFmpeg](https://ffmpeg.org/)
- [Flask](https://flask.palletsprojects.com/)
- [Flask-SocketIO](https://flask-socketio.readthedocs.io/)
