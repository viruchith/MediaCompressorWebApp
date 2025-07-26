import os
import sqlite3
import threading
import logging
import subprocess
import shutil
import json
import mimetypes
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Thread-local database connection
local = threading.local()

def get_db():
    if not hasattr(local, 'conn'):
        local.conn = sqlite3.connect('file_db.db')
    return local.conn

def init_db():
    conn = get_db()
    conn.execute('''
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        input_file_path TEXT NOT NULL UNIQUE,
        output_file_path TEXT NULL,
        compressed INTEGER NOT NULL DEFAULT 0  -- 0: pending, 1: completed, -1: error, 2: processing
    );
    ''')
    conn.commit()

def cleanup_completed_files():
    """Remove completed files from database at startup"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM files WHERE compressed = 1')
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} completed files from database")
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up completed files: {e}")
        return 0

def get_queue_counts():
    """Get counts of files in different states"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get total count
        cursor.execute('SELECT COUNT(*) FROM files')
        total = cursor.fetchone()[0]
        
        # Get pending count
        cursor.execute('SELECT COUNT(*) FROM files WHERE compressed = 0')
        pending = cursor.fetchone()[0]
        
        # Get processing count
        cursor.execute('SELECT COUNT(*) FROM files WHERE compressed = 2')
        processing = cursor.fetchone()[0]
        
        # Get completed count
        cursor.execute('SELECT COUNT(*) FROM files WHERE compressed = 1')
        completed = cursor.fetchone()[0]
        
        # Get error count
        cursor.execute('SELECT COUNT(*) FROM files WHERE compressed = -1')
        errors = cursor.fetchone()[0]
        
        return {
            'total': total,
            'pending': pending,
            'processing': processing,
            'completed': completed,
            'errors': errors
        }
    except Exception as e:
        logger.error(f"Error getting queue counts: {e}")
        return {
            'total': 0,
            'pending': 0,
            'processing': 0,
            'completed': 0,
            'errors': 0
        }

def is_image_file(file_path):
    """Check if file is actually an image using mimetype"""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type and mime_type.startswith('image/')

def is_video_file(file_path):
    """Check if file is actually a video using mimetype"""
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type and mime_type.startswith('video/')

def get_file_extension(file_path):
    """Get file extension in lowercase"""
    return os.path.splitext(file_path)[1][1:].lower()

def compressor_job():
    """Background job to compress files"""
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE compressed = 0')
            files = cursor.fetchall()
            
            # Emit queue counts periodically
            if files:  # Only emit if there are files to process
                counts = get_queue_counts()
                socketio.emit('queue_counts', counts)
            
            for file in files:
                file_id = file[0]
                input_file_path = file[1]
                output_file_path = file[2]
                
                # Emit progress start
                socketio.emit('progress_update', {
                    'file_id': file_id,
                    'status': 'processing',
                    'message': f"Processing {os.path.basename(input_file_path)}"
                })
                
                # Update DB status to processing
                cursor.execute('UPDATE files SET compressed = 2 WHERE id = ?', (file_id,))
                conn.commit()
                
                # Emit updated queue counts
                counts = get_queue_counts()
                socketio.emit('queue_counts', counts)
                
                # Check if input file exists
                if not os.path.exists(input_file_path):
                    logger.error(f"Input file {input_file_path} does not exist.")
                    cursor.execute('UPDATE files SET compressed = -1 WHERE id = ?', (file_id,))
                    conn.commit()
                    socketio.emit('progress_update', {
                        'file_id': file_id,
                        'status': 'error',
                        'message': f"File not found: {input_file_path}"
                    })
                    # Emit updated queue counts
                    counts = get_queue_counts()
                    socketio.emit('queue_counts', counts)
                    continue
                
                try:
                    # Ensure output directory exists
                    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
                    
                    # Get file extension
                    ext = get_file_extension(input_file_path)
                    
                    # Process based on file type
                    if ext in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif', 'webp', 'dng', 'raw', 'cr2', 'nef', 'arw', 'orf', 'sr2', 'raf', 'rw2', 'pef', 'srw']:
                        # Image processing
                        if not is_image_file(input_file_path):
                            logger.warning(f"Skipping non-image file with image extension: {input_file_path}")
                            cursor.execute('UPDATE files SET compressed = -1 WHERE id = ?', (file_id,))
                            conn.commit()
                            socketio.emit('progress_update', {
                                'file_id': file_id,
                                'status': 'error',
                                'message': f"Invalid image file: {os.path.basename(input_file_path)}"
                            })
                            # Emit updated queue counts
                            counts = get_queue_counts()
                            socketio.emit('queue_counts', counts)
                            continue
                        
                        # Determine output format
                        if ext == 'png':
                            out_file = os.path.splitext(output_file_path)[0] + '.png'
                        else:
                            out_file = os.path.splitext(output_file_path)[0] + '.webp'
                        
                        # Ensure output directory exists
                        os.makedirs(os.path.dirname(out_file), exist_ok=True)
                        
                        # ImageMagick compression
                        logger.info(f"Compressing image {input_file_path} to {out_file}")
                        result = subprocess.run([
                            'magick', input_file_path, '-quality', '75', out_file
                        ], capture_output=True, text=True, timeout=300)
                        
                    elif ext in ['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'wmv', 'm4v', '3gp', 'mpeg', 'mpg']:
                        # Video processing
                        if not is_video_file(input_file_path):
                            logger.warning(f"Skipping non-video file with video extension: {input_file_path}")
                            cursor.execute('UPDATE files SET compressed = -1 WHERE id = ?', (file_id,))
                            conn.commit()
                            socketio.emit('progress_update', {
                                'file_id': file_id,
                                'status': 'error',
                                'message': f"Invalid video file: {os.path.basename(input_file_path)}"
                            })
                            # Emit updated queue counts
                            counts = get_queue_counts()
                            socketio.emit('queue_counts', counts)
                            continue
                        
                        # Output as MKV
                        out_file = os.path.splitext(output_file_path)[0] + '.mkv'
                        
                        # Ensure output directory exists
                        os.makedirs(os.path.dirname(out_file), exist_ok=True)
                        
                        # FFmpeg video compression
                        logger.info(f"Compressing video {input_file_path} to {out_file}")
                        result = subprocess.run([
                            'ffmpeg', '-y', '-i', input_file_path,
                            '-c:v', 'libx265', '-preset', 'slow', '-crf', '28',
                            '-c:a', 'aac', '-b:a', '128k', out_file
                        ], capture_output=True, text=True, timeout=1200)  # Longer timeout for videos
                        
                    else:
                        logger.warning(f"Unsupported file type: {input_file_path}")
                        cursor.execute('UPDATE files SET compressed = -1 WHERE id = ?', (file_id,))
                        conn.commit()
                        socketio.emit('progress_update', {
                            'file_id': file_id,
                            'status': 'error',
                            'message': f"Unsupported file type: {os.path.basename(input_file_path)}"
                        })
                        # Emit updated queue counts
                        counts = get_queue_counts()
                        socketio.emit('queue_counts', counts)
                        continue
                    
                    # Check compression result
                    if result.returncode == 0:
                        cursor.execute('UPDATE files SET compressed = 1, output_file_path = ? WHERE id = ?', 
                                     (out_file, file_id,))
                        conn.commit()
                        logger.info(f"Successfully compressed {input_file_path} to {out_file}.")
                        socketio.emit('progress_update', {
                            'file_id': file_id,
                            'status': 'completed',
                            'message': f"Completed: {os.path.basename(input_file_path)}"
                        })
                    else:
                        logger.error(f"Failed to compress {input_file_path}: {result.stderr}")
                        cursor.execute('UPDATE files SET compressed = -1 WHERE id = ?', (file_id,))
                        conn.commit()
                        socketio.emit('progress_update', {
                            'file_id': file_id,
                            'status': 'error',
                            'message': f"Compression failed: {os.path.basename(input_file_path)}"
                        })
                        
                except subprocess.TimeoutExpired:
                    logger.error(f"Timeout compressing {input_file_path}")
                    cursor.execute('UPDATE files SET compressed = -1 WHERE id = ?', (file_id,))
                    conn.commit()
                    socketio.emit('progress_update', {
                        'file_id': file_id,
                        'status': 'error',
                        'message': f"Timeout: {os.path.basename(input_file_path)}"
                    })
                except Exception as e:
                    logger.error(f"Unexpected error compressing {input_file_path}: {e}")
                    cursor.execute('UPDATE files SET compressed = -1 WHERE id = ?', (file_id,))
                    conn.commit()
                    socketio.emit('progress_update', {
                        'file_id': file_id,
                        'status': 'error',
                        'message': f"Error: {str(e)}"
                    })
                
                # Emit updated queue counts after each file
                counts = get_queue_counts()
                socketio.emit('queue_counts', counts)
            
            # Small delay to prevent busy waiting
            socketio.sleep(1)
            
        except Exception as e:
            logger.error(f"Error in compressor job: {e}")
            socketio.sleep(5)

@app.route('/')
def index():
    logger.info("Rendering index page.")
    return render_template('index.html')

@app.route('/files', methods=['GET'])
def get_files():
    try:
        conn = get_db()
        cursor = conn.execute('SELECT * FROM files')
        files = cursor.fetchall()
        logger.info(f"Retrieved {len(files)} files from the database.")
        return jsonify(files)
    except Exception as e:
        logger.error(f"Error retrieving files: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/queue_counts', methods=['GET'])
def get_queue_counts_api():
    """API endpoint to get queue counts"""
    counts = get_queue_counts()
    return jsonify(counts)

@app.route('/folder', methods=['POST'])
def add_folder():
    try:
        input_folder_path = request.form.get('inputFolderPath')
        if not input_folder_path:
            logger.error("No folder path provided.")
            return jsonify({'message': 'No folder path provided.'}), 400
        
        output_folder_path = request.form.get('outputFolderPath')
        if not output_folder_path:
            logger.error("No output folder path provided.")
            return jsonify({'message': 'No output folder path provided.'}), 400
        
        # Check if folders exist
        if not os.path.exists(input_folder_path):
            return jsonify({'message': 'Input folder does not exist.'}), 400
            
        # Create output folder if it doesn't exist
        os.makedirs(output_folder_path, exist_ok=True)
        
        conn = get_db()
        added_files = 0
        
        # Recurse through the folder and add files to the database
        for root, dirs, files in os.walk(input_folder_path):
            for file in files:
                input_file_path = os.path.join(root, file)
                ext = get_file_extension(input_file_path)
                
                # Only process supported image/video files
                supported_extensions = [
                    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif', 'webp', 'dng', 'raw', 
                    'cr2', 'nef', 'arw', 'orf', 'sr2', 'raf', 'rw2', 'pef', 'srw',
                    'mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'wmv', 'm4v', '3gp', 'mpeg', 'mpg'
                ]
                
                if ext not in supported_extensions:
                    logger.info(f"Skipping unsupported file: {input_file_path}")
                    continue
                
                # Generate output file path maintaining the same folder structure
                relative_path = os.path.relpath(input_file_path, input_folder_path)
                output_file_path = os.path.join(output_folder_path, relative_path)
                
                # Insert file into the database
                try:
                    conn.execute('''
                        INSERT INTO files (input_file_path, output_file_path, compressed) 
                        VALUES (?, ?, ?)
                    ''', (input_file_path, output_file_path, 0))
                    added_files += 1
                    logger.info(f"Added file {input_file_path} to the database.")
                except sqlite3.IntegrityError:
                    logger.info(f"File {input_file_path} already exists in the database. Skipping.")
        
        conn.commit()
        logger.info(f"Added {added_files} files from folder {input_folder_path} to the database.")
        
        # Emit updated queue counts
        counts = get_queue_counts()
        socketio.emit('queue_counts', counts)
        
        return jsonify({'message': f'Folder added successfully. {added_files} files queued for compression.'}), 200
        
    except Exception as e:
        logger.error(f"Error adding folder: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/clear_completed', methods=['POST'])
def clear_completed():
    """API endpoint to clear completed files from database"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM files WHERE compressed = 1')
        deleted_count = cursor.rowcount
        conn.commit()
        logger.info(f"Cleared {deleted_count} completed files from database")
        
        # Emit updated queue counts
        counts = get_queue_counts()
        socketio.emit('queue_counts', counts)
        
        return jsonify({'message': f'Cleared {deleted_count} completed files.'}), 200
    except Exception as e:
        logger.error(f"Error clearing completed files: {e}")
        return jsonify({'error': str(e)}), 500

@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")
    emit('connection_status', {'status': 'connected'})
    
    # Send initial queue counts
    counts = get_queue_counts()
    emit('queue_counts', counts)

@socketio.on('disconnect')
def handle_disconnect():
    logger.info("Client disconnected")

@socketio.on('request_queue_counts')
def handle_queue_counts_request():
    """Handle request for queue counts"""
    counts = get_queue_counts()
    emit('queue_counts', counts)

if __name__ == '__main__':
    # Check if required tools are available
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not in PATH")
    
    if not shutil.which("magick"):
        raise RuntimeError("ImageMagick (magick) is not installed or not in PATH")
    
    logger.info("Initializing database...")
    init_db()
    
    logger.info("Cleaning up completed files from previous session...")
    deleted_count = cleanup_completed_files()
    if deleted_count > 0:
        logger.info(f"Removed {deleted_count} completed files from database")
    
    logger.info("Starting compressor job...")
    threading.Thread(target=compressor_job, daemon=True).start()
    
    logger.info("Starting Flask-SocketIO application...")
    socketio.run(app, debug=True, host='0.0.0.0', allow_unsafe_werkzeug=True)