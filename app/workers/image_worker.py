import logging
import mimetypes
import os
import tempfile
from typing import Any, Callable, Dict, Optional

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.config import config
from app.utils.hashing import compute_file_hash

logger = logging.getLogger(__name__)
_heif_registered = False


def _ensure_heif():
    global _heif_registered
    if not _heif_registered:
        register_heif_opener()
        _heif_registered = True


def is_image_file(file_path: str) -> bool:
    mime_type, _ = mimetypes.guess_type(file_path)
    return bool(mime_type and mime_type.startswith("image/"))


def get_output_path(base_output: str, settings: Dict[str, Any]) -> str:
    fmt = settings.get("output_format", "webp")
    if fmt == "jpeg":
        ext = ".jpg"
    else:
        ext = f".{fmt}"
    return os.path.splitext(base_output)[0] + ext


def compress_image(
    input_path: str,
    output_path: str,
    settings: Dict[str, Any],
    progress_callback: Optional[Callable[[int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> tuple:
    """Compress an image atomically. Returns (out_path, input_hash, output_hash, input_size, output_size, ratio)."""
    _ensure_heif()

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Source file does not exist: {input_path}")

    if os.path.getsize(input_path) == 0:
        raise ValueError(f"Cannot compress 0-byte file: {input_path}")

    filename = os.path.basename(input_path)
    if filename.lower().startswith(".trashed"):
        raise ValueError(f"Skipping Android trashed file: {filename}")

    if not is_image_file(input_path):
        raise ValueError(f"Not a valid image file: {input_path}")

    out_path = get_output_path(output_path, settings)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if progress_callback:
        progress_callback(10, "Computing input hash")

    if should_cancel and should_cancel():
        raise InterruptedError("Image compression cancelled")

    # Pass cancellation callback to hash computation for interruptibility
    input_hash = compute_file_hash(input_path, should_cancel=should_cancel)
    input_size = os.path.getsize(input_path)

    quality = settings.get("quality", 75)
    lossless = settings.get("lossless", False)
    max_dim = settings.get("max_dimension")
    strip_metadata = settings.get("strip_metadata", False)
    fmt = settings.get("output_format", "webp")
    if fmt == "jpeg":
        pil_format = "JPEG"
    elif fmt == "png":
        pil_format = "PNG"
    elif fmt == "avif":
        pil_format = "AVIF"
    else:
        pil_format = "WEBP"

    if progress_callback:
        progress_callback(20, "Opening image")

    with Image.open(input_path) as raw_img:
        img = ImageOps.exif_transpose(raw_img)
        exif = img.info.get("exif")
        icc = img.info.get("icc_profile")

        if max_dim:
            w, h = img.size
            if max(w, h) > max_dim:
                ratio = max_dim / max(w, h)
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                if progress_callback:
                    progress_callback(40, f"Resized to {new_size[0]}x{new_size[1]}")

        # Color mode & alpha handling
        if pil_format == "JPEG":
            # JPEG cannot carry alpha; flatten transparency against white background
            if img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
        elif pil_format in ("WEBP", "PNG", "AVIF"):
            # WebP, PNG, and AVIF support alpha natively; normalize palette mode
            if img.mode == "P":
                img = img.convert("RGBA" if "transparency" in img.info else "RGB")

        save_kwargs: Dict[str, Any] = {"optimize": True}
        if strip_metadata:
            exif = None
            icc = None
        else:
            if exif:
                save_kwargs["exif"] = exif
            if icc:
                save_kwargs["icc_profile"] = icc

        if pil_format == "WEBP":
            save_kwargs["method"] = 6
            if lossless:
                save_kwargs["lossless"] = True
            else:
                save_kwargs["quality"] = quality
        elif pil_format == "JPEG":
            save_kwargs["quality"] = quality
        elif pil_format == "PNG":
            save_kwargs["compress_level"] = 9
        elif pil_format == "AVIF":
            save_kwargs["quality"] = quality

        if progress_callback:
            progress_callback(60, "Compressing")

        if should_cancel and should_cancel():
            raise InterruptedError("Image compression cancelled")

        fd, tmp_path = tempfile.mkstemp(
            suffix=os.path.splitext(out_path)[1],
            dir=os.path.dirname(out_path) or ".",
        )
        os.close(fd)
        try:
            img.save(tmp_path, pil_format, **save_kwargs)
            if progress_callback:
                progress_callback(90, "Finalizing")
            os.replace(tmp_path, out_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    output_size = os.path.getsize(out_path)
    output_hash = compute_file_hash(out_path)
    ratio = output_size / input_size if input_size > 0 else 0

    if progress_callback:
        progress_callback(100, "Complete")

    return out_path, input_hash, output_hash, input_size, output_size, ratio
