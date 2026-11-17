"""Avatars and images used by the Streamlit UI."""

import base64
import io
import logging
import os

import streamlit as st
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

ICON_PATH = "./static/icon1.png"


def load_page_icon():
    """Browser-tab icon: the LEA image, or an emoji if it's missing."""
    try:
        if os.path.exists(ICON_PATH):
            return Image.open(ICON_PATH).resize((32, 32), Image.Resampling.LANCZOS)
    except Exception as e:
        logger.debug(f"Error loading page icon: {e}")
    return "🎓"


@st.cache_data
def create_student_avatar(initial: str) -> Image.Image:
    """Create a circular avatar with student's initial - cached for performance"""
    size = 50
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Light blue background (#ADD8E6)
    light_blue = (173, 216, 230)
    draw.ellipse([0, 0, size, size], fill=light_blue)
    
    # Try to load Arial font with fallbacks for different systems
    font_size = 36
    try:
        # Windows - Load Arial Bold
        font = ImageFont.truetype("arialbd.ttf", font_size)  # <-- CHANGED: arialbd.ttf for bold
    except OSError:
        try:
            # macOS - Load Helvetica Bold or Arial Bold
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size, index=1)  # index=1 for bold
        except OSError:
            try:
                # Try Arial Bold on macOS
                font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", font_size)
            except OSError:
                try:
                    # Linux - Already using Bold variant
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except OSError:
                    try:
                        # Alternative Linux bold font
                        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", font_size)
                    except OSError:
                        # Fallback to default font
                        font = ImageFont.load_default()    
    # Get text bounding box for centering
    initial_upper = initial.upper()
    bbox = draw.textbbox((0, 0), initial_upper, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Center the text
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - 2  # Slight adjustment for better centering
    
    # Draw black bold text
    draw.text((x, y), initial_upper, fill='black', font=font)
    
    return img

@st.cache_data
def get_lea_avatar() -> Image.Image:
    """Get resized LEA avatar - cached for performance"""
    lea_avatar_path = "./static/icon1.png"
    
    try:
        if os.path.exists(lea_avatar_path):
            # Load and resize the image
            img = Image.open(lea_avatar_path)
            img = img.resize((50, 50), Image.Resampling.LANCZOS)
            
            # Convert to RGBA if not already
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            return img
        else:
            logger.debug(f"LEA avatar not found at {lea_avatar_path}")
            return create_fallback_lea_avatar()
    except Exception as e:
        logger.debug(f"Error loading LEA avatar: {e}")
        return create_fallback_lea_avatar()

@st.cache_data
def create_fallback_lea_avatar() -> Image.Image:
    """Create a fallback LEA avatar if image file not found"""
    size = 50
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Purple background for LEA
    purple = (138, 43, 226)
    draw.ellipse([0, 0, size, size], fill=purple)
    
    # Draw "LEA" text
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    
    text = "LEA"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (size - text_width) // 2
    y = (size - text_height) // 2
    
    draw.text((x, y), text, fill='white', font=font)
    
    return img

def pil_image_to_base64(img: Image.Image) -> str:
    """Convert PIL image to base64 string for HTML display"""
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    img_b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{img_b64}"
