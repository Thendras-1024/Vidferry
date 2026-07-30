"""版本二封面片头的图像分析、ASS 生成与 FFmpeg 参数构造。"""

from __future__ import annotations

import re
from pathlib import Path

from app.utils.ffmpeg_util import video_encode_args


COVER_EXTENSIONS = (".webp", ".jpg", ".jpeg", ".png")
DEFAULT_COVER_SIGNATURE = "Vidferry"


def normalize_cover_title(value):
    text = str(value or "").replace("\r", "\n").replace("#", "").strip()
    lines = [line.strip(" ，,。.!！?？:：|｜") for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) == 1 and len(lines[0]) > 8:
        source = lines[0]
        split_points = [
            index for index, char in enumerate(source)
            if char in "，,。.!！?？:：|｜" and 3 <= index <= len(source) - 4
        ]
        split_at = min(split_points, key=lambda item: abs(item - len(source) / 2)) if split_points else len(source) // 2
        lines = [source[:split_at], source[split_at + 1:] if source[split_at] in "，,。.!！?？:：|｜" else source[split_at:]]
    elif len(lines) > 2:
        lines = [lines[0], "".join(lines[1:])]
    return "\n".join(line.strip()[:12] for line in lines[:2] if line.strip())


def normalize_cover_context(value):
    return re.sub(r"[#\r\n]+", "", str(value or "")).strip()[:8]


def normalize_cover_signature(value):
    signature = re.sub(r"[\r\n]+", " ", str(value or "")).strip()[:24]
    return signature or DEFAULT_COVER_SIGNATURE


def find_cover_image(download_dir, video_id="", source_file=""):
    project_root = Path(__file__).resolve().parents[2]

    def resolve_path(value):
        path = Path(value)
        return path if path.is_absolute() else project_root / path

    candidates = []
    if source_file:
        candidates.append(resolve_path(source_file))
    if video_id:
        candidates.append(resolve_path(download_dir) / str(video_id))
    for candidate in candidates:
        for extension in COVER_EXTENSIONS:
            path = candidate.with_suffix(extension)
            if path.is_file():
                return path
    return None


def _crop_black_borders(image):
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = cv2.threshold(gray, 12, 255, cv2.THRESH_BINARY)[1]
    points = cv2.findNonZero(mask)
    height, width = gray.shape
    if points is None:
        return image, (0, 0, width, height)
    x, y, crop_width, crop_height = cv2.boundingRect(points)
    retained = (crop_width * crop_height) / float(width * height or 1)
    if retained < 0.55 or (x < width * 0.015 and y < height * 0.015 and crop_width > width * 0.97 and crop_height > height * 0.97):
        return image, (0, 0, width, height)
    return image[y:y + crop_height, x:x + crop_width], (x, y, crop_width, crop_height)


def _fill_canvas(image, width, height):
    import cv2

    source_height, source_width = image.shape[:2]
    scale = max(width / float(source_width or 1), height / float(source_height or 1))
    resized_width = max(width, int(round(source_width * scale)))
    resized_height = max(height, int(round(source_height * scale)))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LANCZOS4)
    offset_x = max(0, (resized_width - width) // 2)
    offset_y = max(0, (resized_height - height) // 2)
    return resized[offset_y:offset_y + height, offset_x:offset_x + width]


def _candidate_layouts(width, height):
    if height > width:
        return [
            ("bottom_full", 0.07, 0.58, 0.86, 0.30, "center"),
            ("top_full", 0.07, 0.10, 0.86, 0.30, "center"),
            ("middle_full", 0.07, 0.36, 0.86, 0.30, "center"),
        ]
    return [
        ("bottom_full", 0.05, 0.58, 0.90, 0.32, "center"),
        ("top_full", 0.05, 0.08, 0.90, 0.32, "center"),
        ("left_stack", 0.05, 0.30, 0.56, 0.42, "left"),
        ("right_stack", 0.39, 0.30, 0.56, 0.42, "right"),
    ]


def _palette_for_region(region):
    import cv2

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue = float(hsv[..., 0].mean())
    saturation = float(hsv[..., 1].mean())
    if saturation > 65 and (hue < 28 or hue > 165):
        return ("&H00FFE600", "&H00FFFFFF")
    if saturation > 55 and 85 <= hue <= 140:
        return ("&H0000E6FF", "&H00FFFFFF")
    return ("&H0000E6FF", "&H00FFE600")


def analyze_cover_layout(cover_path, width, height, cover_title):
    import cv2
    import numpy as np

    image = cv2.imread(str(cover_path))
    if image is None:
        raise ValueError(f"无法读取封面图片 : {cover_path}")
    cropped, source_crop = _crop_black_borders(image)
    canvas = _fill_canvas(cropped, max(320, int(width)), max(320, int(height)))
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 180)

    face_mask = np.zeros_like(gray)
    if hasattr(cv2, "CascadeClassifier") and getattr(cv2, "data", None):
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
        min_side = max(30, min(width, height) // 18)
        for x, y, face_width, face_height in cascade.detectMultiScale(gray, 1.08, 4, minSize=(min_side, min_side)):
            padding_x = int(face_width * 0.35)
            padding_y = int(face_height * 0.35)
            cv2.rectangle(
                face_mask,
                (max(0, x - padding_x), max(0, y - padding_y)),
                (min(width, x + face_width + padding_x), min(height, y + face_height + padding_y)),
                255,
                -1,
            )

    gradient = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    _, text_seed = cv2.threshold(gradient, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, width // 35), max(3, height // 180)))
    text_mask = cv2.morphologyEx(text_seed, cv2.MORPH_CLOSE, kernel)

    scored = []
    for layout_id, nx, ny, nw, nh, alignment in _candidate_layouts(width, height):
        x, y = int(width * nx), int(height * ny)
        box_width, box_height = int(width * nw), int(height * nh)
        region = gray[y:y + box_height, x:x + box_width]
        face_overlap = float(face_mask[y:y + box_height, x:x + box_width].mean()) / 255.0
        edge_density = float(edges[y:y + box_height, x:x + box_width].mean()) / 255.0
        text_density = float(text_mask[y:y + box_height, x:x + box_width].mean()) / 255.0
        contrast = min(1.0, float(region.std()) / 90.0)
        replace_text = text_density > 0.24 and face_overlap < 0.08
        score = face_overlap * 9.0 + edge_density * 1.8 + contrast * 0.45
        if replace_text:
            score -= min(0.55, text_density) * 0.9
        scored.append({
            "id": layout_id,
            "x": x,
            "y": y,
            "width": box_width,
            "height": box_height,
            "alignment": alignment,
            "score": round(score, 4),
            "faceOverlap": round(face_overlap, 4),
            "textDensity": round(text_density, 4),
            "plate": bool(replace_text or edge_density > 0.20 or contrast > 0.72),
            "palette": _palette_for_region(canvas[y:y + box_height, x:x + box_width]),
        })

    scored.sort(key=lambda item: item["score"])
    selected = dict(scored[0])
    gap = scored[1]["score"] - selected["score"] if len(scored) > 1 else 1.0
    if selected["faceOverlap"] > 0.12 or selected["score"] > 1.3:
        selected = next(dict(item) for item in scored if item["id"] == "bottom_full")
        selected["plate"] = True
        selected["fallback"] = True
    else:
        selected["fallback"] = False

    lines = normalize_cover_title(cover_title).splitlines() or [""]
    longest_line = max(len(line) for line in lines)
    short_side = min(width, height)
    size_by_height = int(selected["height"] * (0.30 if len(lines) > 1 else 0.48))
    size_by_width = int(selected["width"] / max(4.8, longest_line * 1.05))
    selected["fontSize"] = max(int(short_side * 0.055), min(int(short_side * 0.12), size_by_height, size_by_width))
    selected["confidence"] = round(max(0.0, min(1.0, 0.55 + gap - selected["score"] * 0.18)), 3)
    selected["sourceCrop"] = {
        "x": int(source_crop[0]),
        "y": int(source_crop[1]),
        "width": int(source_crop[2]),
        "height": int(source_crop[3]),
    }
    return selected


def _ass_timestamp(seconds):
    seconds = max(0.0, float(seconds or 0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _ass_text(value):
    return str(value or "").replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _cover_text_width(text, font_size):
    units = sum(1.0 if ord(char) >= 0x2E80 else 0.55 for char in str(text or ""))
    return int(units * float(font_size) * 0.78)


def write_cover_ass(ass_file, width, height, duration, cover_title, layout, signature=DEFAULT_COVER_SIGNATURE, watermark_text=""):
    ass_file = Path(ass_file)
    lines = normalize_cover_title(cover_title).splitlines()
    if not lines:
        raise ValueError("封面标题不能为空")
    if len(lines) == 1:
        lines.append("")

    alignment = layout.get("alignment") or "center"
    if alignment == "left":
        ass_alignment, x = 4, layout["x"] + int(layout["width"] * 0.04)
    elif alignment == "right":
        ass_alignment, x = 6, layout["x"] + int(layout["width"] * 0.96)
    else:
        ass_alignment, x = 5, layout["x"] + layout["width"] // 2
    first_y = layout["y"] + int(layout["height"] * (0.36 if lines[1] else 0.50))
    second_y = layout["y"] + int(layout["height"] * 0.72)
    font_size = int(layout["fontSize"])
    info_size = font_size
    outline = max(3, round(font_size * 0.065, 1))
    end = _ass_timestamp(duration)
    primary, secondary = layout.get("palette") or ("&H0000D6FF", "&H00F5F5F5")
    signature = f"@{normalize_cover_signature(signature).lstrip('@')}"
    title_width = _cover_text_width(lines[0], font_size)
    title_right = x + title_width // 2 if alignment == "center" else x + title_width if alignment == "left" else x
    signature_half_width = _cover_text_width(signature, info_size) // 2
    signature_x = max(signature_half_width + 24, min(width - signature_half_width - 24, title_right))
    signature_y = max(info_size + 24, first_y - int(font_size * 0.30))
    watermark_text = _ass_text(watermark_text)
    watermark_size = max(20, min(54, int(min(width, height) * 0.032)))
    watermark_margin = max(20, int(width * 0.042))
    watermark_margin_v = max(40, int(height * 0.070))

    content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: CoverPrimary,Microsoft YaHei,{font_size},{primary},&H000000FF,&H00000000,&HFF000000,1,0,0,0,100,100,0,0,1,{outline},2.6,5,0,0,0,1",
        f"Style: CoverSecondary,Microsoft YaHei,{font_size},{secondary},&H000000FF,&H00000000,&HFF000000,1,0,0,0,100,100,0,0,1,{outline},2.6,5,0,0,0,1",
        f"Style: CoverSignature,Microsoft YaHei,{info_size},&H00F5F5F5,&H000000FF,&H00000000,&HFF000000,1,0,0,0,100,100,0,0,1,1.5,1.4,4,0,0,0,1",
        f"Style: Watermark,Microsoft YaHei,{watermark_size},&HD9FFFFFF,&H000000FF,&HE6000000,&H00000000,0,0,0,0,100,100,0,-15,1,1,0,9,{watermark_margin},{watermark_margin},{watermark_margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 2,0:00:00.00,{end},CoverPrimary,,0,0,0,,{{\\an{ass_alignment}\\pos({x},{first_y})}}{_ass_text(lines[0])}",
    ]
    if lines[1]:
        content.append(f"Dialogue: 2,0:00:00.00,{end},CoverSecondary,,0,0,0,,{{\\an{ass_alignment}\\pos({x},{second_y})}}{_ass_text(lines[1])}")
    content.append(f"Dialogue: 3,0:00:00.00,{end},CoverSignature,,0,0,0,,{{\\an2\\pos({signature_x},{signature_y})}}{_ass_text(signature)}")
    if watermark_text:
        content.append(f"Dialogue: 4,0:00:00.00,{end},Watermark,,0,0,0,,{watermark_text}")
    ass_file.write_text("\n".join(content), encoding="utf-8")
    return ass_file


def _filter_path(path):
    return Path(path).resolve().as_posix().replace(":", r"\:").replace("'", r"\'")


def build_cover_clip_command(ffmpeg, cover_path, ass_file, output_file, width, height, fps, duration, burn_config, layout, has_audio=True, color_info=None):
    crop = layout.get("sourceCrop") or {}
    filters = []
    if crop.get("width") and crop.get("height"):
        filters.append(f"crop={crop['width']}:{crop['height']}:{crop.get('x', 0)}:{crop.get('y', 0)}")
    filters.extend([
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={width}:{height}",
        "setsar=1",
    ])
    filters.append(f"subtitles='{_filter_path(ass_file)}'")

    fps_text = f"{float(fps):.3f}".rstrip("0").rstrip(".")
    command = [
        str(ffmpeg), "-y", "-loop", "1", "-framerate", fps_text, "-t", f"{float(duration):.3f}", "-i", str(cover_path),
    ]
    if has_audio:
        command.extend(["-f", "lavfi", "-t", f"{float(duration):.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
    command.extend(["-map", "0:v:0"])
    if has_audio:
        command.extend(["-map", "1:a:0"])
    command.extend([
        "-vf", ",".join(filters),
        "-fps_mode", "cfr", "-r", fps_text,
        *video_encode_args(burn_config),
        "-maxrate", burn_config["maxrate"], "-bufsize", burn_config["bufsize"],
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", burn_config.get("h264_level", "4.1"),
    ])
    color_info = color_info if isinstance(color_info, dict) else {}
    if color_info.get("space") and color_info.get("primaries") and color_info.get("transfer"):
        command.extend([
            "-x264-params",
            f"colorprim={color_info['primaries']}:transfer={color_info['transfer']}:colormatrix={color_info['space']}",
            "-colorspace", color_info["space"],
            "-color_primaries", color_info["primaries"],
            "-color_trc", color_info["transfer"],
        ])
    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest"])
    else:
        command.append("-an")
    command.extend(["-movflags", "+faststart", str(output_file)])
    return command
