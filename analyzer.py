from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Literal, Optional

import imagehash
import pytesseract
import requests
from PIL import Image, ImageGrab, ImageOps

# Assuming these are correctly defined in models.py with the 'self' fix
# and AnalysisReport is a simple data class for results.
from models import AnalysisReport, DecodeResult, Pattern, Song, ArchiveException

if getattr(sys, "frozen", False):
    BASEDIR = os.path.dirname(sys.executable)
else:
    BASEDIR = os.path.dirname(os.path.abspath(__file__))
os.environ["TESSDATA_PREFIX"] = os.path.join(BASEDIR, "tesseract", "tessdata")

# --- CONFIGURATION CONSTANTS ---
# Use one dictionary for all ROI ratios for better maintainability.
# The keys correspond to the variable names used in the original code.
# Format: (x_start, y_start, x_end, y_end) or (x, y) for single point.
REF_W, REF_H = 1920, 1080

ROI_CONFIG = {
    "SELECT": {
        "jacket": (760, 66, 1160, 466),
        "major_judge": (979, 846, 1015, 865),
        "minor_judge": (1019, 848, 1059, 865),
        "line": (143, 32, 361, 78),
        "major_patch": (891, 741, 1026, 786),
        "minor_patch": (1032, 752, 1078, 786),
        "score": (961, 803, 1078, 826),
        "full_combo": (1109, 867, 1320, 900),
        "max_patch": (1033, 726),
        "rank": (1151, 684, 1280, 812),
    },
    "RESULT": {
        # Bounding Boxes (x_start, y_start, x_end, y_end)
        "jacket": (122, 193, 522, 593),
        "judge": (959, 301, 1283, 367),
        "line": (37, 32, 75, 81),
        "level": (395, 700, 502, 762),
        "patch": (979, 186, 1320, 251),
        "score": (953, 418, 1316, 483),
        "rank": (1020, 575, 1345, 890),
        "notes_area": (874, 0, 950, 0),  # Placeholder for common X
        # Notes Y-Coordinates (start_y, end_y) for fixed X (notes_area)
        "total_notes": (589, 614),
        "perfect_high_y": (650, 675),
        "perfect_y": (686, 713),
        "great_y": (725, 751),
        "good_y": (764, 788),
        "miss_y": (800, 828),
        # Single Points (x, y)
        "difficulty_color": (300, 730),
    },
}

# Use a dictionary for color templates for maintainability
DIFFICULTY_COLORS = {
    "EASY": (254, 179, 26),
    "HARD": (252, 109, 111),
    "OVER": (187, 99, 219),
    "PLUS": (69, 81, 141),
}
COLOR_TOLERANCE = 5  # Use a small tolerance for minor compression changes


# --- CORE ANALYZER CLASS ---


class ScreenshotAnalyzer:
    """
    Manages the data fetching, scaling, OCR, and analysis logic.
    """

    def __init__(self, song_database: list[Song]):
        tesseract_exe_path = os.path.join(BASEDIR, "tesseract", "tesseract.exe")
        pytesseract.pytesseract.tesseract_cmd = tesseract_exe_path
        self.song_db: dict[int, Song] = {song.id: song for song in song_database}
        self.jacket_hash_map: dict[str, Song] = self._build_jacket_hash_map()
        self.PHASH_THRESHOLD = 5

    # --- Setup Methods ---

    def _build_jacket_hash_map(self) -> dict[str, Song]:
        """Creates a map of pHash strings to Song objects for quick lookup."""
        hash_map = {}
        for song in self.song_db.values():
            if song.phash:
                hash_map[song.phash] = song
            if song.plus_phash:
                hash_map[song.plus_phash] = song
        return hash_map

    # --- Static Helper Methods ---

    @staticmethod
    def _ratio(x: int, y: int) -> tuple[float, float]:
        """Calculates normalized coordinates relative to 1920x1080."""
        return x / REF_W, y / REF_H

    @staticmethod
    def _scale_coordinate(
        ratio_x: float, ratio_y: float, size: tuple[int, int]
    ) -> tuple[int, int]:
        """Scales normalized coordinates to the current screenshot size."""
        user_width, user_height = size
        abs_x = int(round(user_width * ratio_x))
        abs_y = int(round(user_height * ratio_y))
        return abs_x, abs_y

    @staticmethod
    def determine_screen_type(screenshot: Image.Image) -> Literal["SELECT", "RESULT"]:
        select_speed_start = (30, 908)
        select_speed_end = (119, 932)
        select_speed_crop = screenshot.crop(select_speed_start + select_speed_end)
        select_speed_hash = imagehash.phash(select_speed_crop)
        hashed_select_speed = "c0c73d38273ed2c3"
        if select_speed_hash - imagehash.hex_to_hash(hashed_select_speed) < 5:
            return "SELECT"
        else:
            return "RESULT"

    @staticmethod
    def read_selected_level_by_phash(img: Image.Image):
        level_hash_map = {
            5: "ea66a51ad2696497",
            7: "eb4ae42dc42eb196",
            15: "e87c8d02d369c697",
            19: "e87a8d09cd699297",
            21: "f26aad11d327849d",
        }
        phash = imagehash.phash(img)
        print(phash)
        for level, level_hash in level_hash_map.items():
            level_hash = imagehash.hex_to_hash(level_hash)
            if phash - level_hash < 3:
                return level
        return 0

    @staticmethod
    def is_pivot_pixel(rgb: tuple[int, int, int]):
        # easy
        if abs(rgb[0] - 231) < 5 and abs(rgb[1] - 136) < 5 and abs(rgb[2] - 40) < 5:
            return "EASY"
        elif abs(rgb[0] - 234) < 5 and abs(rgb[1] - 98) < 5 and abs(rgb[2] - 124) < 5:
            return "HARD"
        elif abs(rgb[0] - 146) < 5 and abs(rgb[1] - 115) < 5 and abs(rgb[2] - 254) < 5:
            return "OVER"
        elif abs(rgb[0] - 31) < 5 and abs(rgb[1] - 45) < 5 and abs(rgb[2] - 90) < 5:
            return "PLUS"
        else:
            return None

    def _analyze_select_screen(self, img: Image.Image) -> AnalysisReport:
        screen_type = "SELECT"
        # 1. Get Base Data (Jacket and Match Song)
        jacket_crop = self._crop_and_ocr(
            img, screen_type, "jacket", lambda x: x, no_preprocess=True
        )
        # jacket_crop.save("out.png")
        jacket_hash = imagehash.phash(jacket_crop)
        matched_song, match_distance = self.get_best_match_song(jacket_hash)

        if match_distance > 5:
            raise ArchiveException(
                "노래 재킷 인식 실패. 인식할 수 없는 화면이거나 노래가 아직 DB에 등록되지 않았습니다."
            )

        # 2. Extract Lines and Base Difficulty Color (if available on select screen)
        line = self._crop_and_ocr(img, screen_type, "line", self.get_ocr_line)
        score = self._crop_and_ocr(img, screen_type, "score", self.get_ocr_integer)
        major_patch = self._crop_and_ocr(
            img, screen_type, "major_patch", self.get_ocr_select_major_patch
        )
        minor_patch = self._crop_and_ocr(
            img, screen_type, "minor_patch", self.get_ocr_select_minor_patch
        )
        if minor_patch < 10:
            minor_patch = f"0{minor_patch}"
        patch = float(f"{major_patch}.{minor_patch}")

        major_judge = self._crop_and_ocr(
            img, screen_type, "major_judge", self.get_ocr_integer
        )
        minor_judge = self._crop_and_ocr(
            img, screen_type, "minor_judge", self.get_ocr_select_minor_judge
        )
        minor_judge = "0" * (4 - len(str(minor_judge))) + str(minor_judge)
        judge = float(f"{major_judge}.{minor_judge}")

        is_full_combo = False
        is_perfect_decode = False
        is_max_patch = False

        # Iterate until it founds the arrow
        pivot_x = 843
        pivot_y = 627
        pivot_found = False
        while pivot_y < 1040:
            abs_coords = self._get_abs_coords(
                (pivot_x, pivot_y, pivot_x, pivot_y), img.size
            )
            pivot_pixel = img.getpixel((abs_coords[0], abs_coords[1]))
            difficulty = self.is_pivot_pixel(pivot_pixel)
            if difficulty:
                pivot_found = True
                level_start_x = pivot_x
                if difficulty == "UNKNOWN":
                    difficulty = "PLUS"
                level_start_x = pivot_x - 105
                level_start_y = pivot_y + 29
                level_end_x = pivot_x
                level_end_y = pivot_y + 95
                level_abs_coords = self._get_abs_coords(
                    (level_start_x, level_start_y, level_end_x, level_end_y), img.size
                )
                level_crop = img.crop(level_abs_coords)
                level_crop = self.ocr_preprocess(level_crop, do_invert=True)
                # level_crop.show()
                level = self.get_ocr_integer(level_crop)
                print(f"OCRed Level: {level}")
                available_levels = matched_song.get_available_levels(line, difficulty)
                if len(available_levels) == 1:
                    level = available_levels[0]
                if not level in available_levels:
                    level = self.read_selected_level_by_phash(level_crop)
                break
            pivot_y += 1

        if not pivot_found:
            print("Pivot not found")

        full_combo_crop = self._crop_and_ocr(
            img, screen_type, "full_combo", lambda x: x, no_preprocess=True
        )
        hashed_full_combo = imagehash.hex_to_hash("8a82953d9d376b1a")
        # full_combo_crop.show()
        full_combo_hash = imagehash.phash(full_combo_crop)
        if full_combo_hash - hashed_full_combo < 5:
            is_full_combo = True

        if judge == 100:
            is_full_combo = True
            is_perfect_decode = True

        max_patch_pixel = img.getpixel(ROI_CONFIG[screen_type]["max_patch"])
        if (
            abs(max_patch_pixel[0] - 200) < 5
            and abs(max_patch_pixel[1] - 111) < 5
            and abs(max_patch_pixel[2] - 254) < 5
        ):
            is_max_patch = True

        rank_crop = self._crop_and_ocr(
            img, screen_type, "rank", lambda x: x, no_preprocess=True
        )
        # rank_crop.show()
        rank_hash = imagehash.phash(rank_crop)
        hashed_f_rank = imagehash.hex_to_hash("bb604083cfda63a7")

        rank = self.calculate_rank(judge)
        if rank_hash - hashed_f_rank < 5:
            rank = "F"
        # 4. Return Report (Use N/A for missing result screen stats)
        return AnalysisReport(
            matched_song,
            score,
            judge,
            patch,
            line,
            difficulty,
            level,
            jacket_crop,
            jacket_hash,
            match_distance,
            rank,
            is_full_combo,
            is_perfect_decode,
            is_max_patch,
        )

    def _crop_and_ocr(
        self,
        img: Image.Image,
        screen_type: Literal["SELECT", "RESULT"],
        config_key: str,
        ocr_func,
        is_point=False,
        no_preprocess=False,
        **kwargs,
    ):
        """Helper to handle scaling, cropping, and running OCR."""
        size = img.size
        ref_coords = ROI_CONFIG[screen_type][config_key]
        if is_point:
            rx, ry = self._ratio(ref_coords[0], ref_coords[1])
            abs_x, abs_y = self._scale_coordinate(rx, ry, size)
            return ocr_func(img, abs_x, abs_y, **kwargs)  # Call color/point function

        # Handle notes area with common X but separate Y
        elif config_key in [
            "perfect_high_y",
            "perfect_y",
            "great_y",
            "good_y",
            "miss_y",
            "total_notes",
        ]:
            notes_x = ROI_CONFIG[screen_type]["notes_area"]
            rx0, rxf = self._ratio(notes_x[0], 0)[0], self._ratio(notes_x[2], 0)[0]
            ry0, ryf = (
                self._ratio(0, ref_coords[0])[1],
                self._ratio(0, ref_coords[1])[1],
            )
        else:
            # Bounding box logic
            rx0, ry0 = self._ratio(ref_coords[0], ref_coords[1])
            rxf, ryf = self._ratio(ref_coords[2], ref_coords[3])

        abs_x0, abs_y0 = self._scale_coordinate(rx0, ry0, size)
        abs_xf, abs_yf = self._scale_coordinate(rxf, ryf, size)

        crop = img.crop((abs_x0, abs_y0, abs_xf, abs_yf))
        if no_preprocess:
            return ocr_func(crop, **kwargs)
        # do preprocess for better OCR result
        crop = self.ocr_preprocess(crop, **kwargs)
        return ocr_func(crop, **kwargs)

    # --- OCR / Matching Functions (Moved from global scope) ---

    def get_best_match_song(
        self, target_hash: imagehash.ImageHash
    ) -> tuple[Optional[Song], int]:
        """Finds the Song object corresponding to the target pHash."""
        min_distance = float("inf")
        best_match_song = None

        for phash_str, song_obj in self.jacket_hash_map.items():
            # Tesseract 5 hash format is used for consistency
            ref_hash = imagehash.hex_to_hash(phash_str)
            distance = target_hash - ref_hash

            if distance < min_distance:
                min_distance = distance
                best_match_song = song_obj
        return best_match_song, min_distance

    @staticmethod
    def get_ocr_judge(img_crop: Image.Image) -> float:
        """OCR for judge percentage (e.g., 99.0000%)."""
        # Fix: Char whitelist spelling
        ocr_config = r"--psm 7 -c tessedit_char_whitelist=0123456789.%"
        text = pytesseract.image_to_string(img_crop, config=ocr_config).strip()

        # Cleanup and convert to float
        text = text.replace("%", "")
        try:
            return float(text)
        except ValueError:
            return 0.0

    @staticmethod
    def get_ocr_line(img_crop: Image.Image) -> int:
        """OCR for line count (4, 6). If no text, assume 6."""
        # Whitelist 4, 6, and 8
        ocr_config = r"--psm 7 -c tessedit_char_whitelist=46"
        text = pytesseract.image_to_string(img_crop, config=ocr_config).strip()

        # Fallback logic: if OCR is empty, assume 6 (a common game logic)
        try:
            return int(text)
        except ValueError:
            return 6

    @staticmethod
    def get_ocr_integer(img_crop: Image.Image, **kwargs) -> int:
        """OCR for pure integer values (Level, Score, Notes)."""
        config = "--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(img_crop, config=config).strip()
        try:
            return int(text)
        except ValueError:
            level_img_phash = imagehash.phash(img_crop)
            print(f"Error when converting the text to str: '{text}'")
            print(f"Read pHash: {level_img_phash}")
            print(f"Trying to read it by pHash...")
            return ScreenshotAnalyzer.find_level_phash(img_crop)

    @staticmethod
    def get_ocr_select_major_patch(img_crop: Image.Image, **kwargs) -> int:
        config = "--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(img_crop, config=config).strip()
        phash = imagehash.phash(img_crop)
        print(f"Major Patch PHash: {phash}")
        phash_map = {
            609: "f3738c6596f2218c",
            610: "f3738e6696a3218c",
            627: "e151ca6616e93b9c",
            637: "e1518e6216e52f9e",
            641: "f3f19a622c93698c",
            642: "f371966a2ad2658c",
            661: "e3619a63af61619c",
            670: "f3698c662cb3338c",
            671: "f3698c662cf3138c",
            676: "f36b8c6405f2738c",
        }
        lowest_distance = 50
        possible_patch = ""
        for patch, known_phash in phash_map.items():
            known_phash = imagehash.hex_to_hash(known_phash)
            distance = phash - known_phash
            if distance < lowest_distance:
                lowest_distance = distance
                possible_patch = patch
        if lowest_distance < 3:
            return possible_patch
        try:
            return int(text)
        except ValueError:
            return 0

    @staticmethod
    def get_ocr_select_minor_patch(img_crop: Image.Image, **kwargs) -> int:
        config = "--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(img_crop, config=config).strip()
        phash = imagehash.phash(img_crop)
        print(f"Minor Patch PHash: {phash}")
        phash_map = {22: "ae78d02f0dac78d2", 88: "aa2ad5ad52cc2cd3"}
        lowest_distance = 50
        possible_patch = ""
        for patch, known_phash in phash_map.items():
            known_phash = imagehash.hex_to_hash(known_phash)
            distance = phash - known_phash
            if distance < lowest_distance:
                lowest_distance = distance
                possible_patch = patch
        if lowest_distance < 3:
            return possible_patch
        try:
            return int(text)
        except ValueError:
            return 0

    @staticmethod
    def get_ocr_select_minor_judge(img_crop: Image.Image, **kwargs) -> int:
        config = "--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(img_crop, config=config).strip()
        phash = imagehash.phash(img_crop)
        print(f"Minor Judge PHash: {phash}")
        phash_map = {5277: "9dc1aabc8183ec3b", 5572: "9be4e6ea9110ee13"}
        lowest_distance = 50
        possible_patch = ""
        for patch, known_phash in phash_map.items():
            known_phash = imagehash.hex_to_hash(known_phash)
            distance = phash - known_phash
            if distance < lowest_distance:
                lowest_distance = distance
                possible_patch = patch
        if lowest_distance < 3:
            return possible_patch
        try:
            return int(text)
        except ValueError:
            return 0

    @staticmethod
    def get_ocr_patch(img_crop: Image.Image, **kwargs) -> float:
        """OCR for patch value (e.g., 2.79)."""
        config = "--psm 7 -c tessedit_char_whitelist=0123456789."
        text = pytesseract.image_to_string(img_crop, config=config).strip()

        # Post-processing fix for patch if the decimal is missed
        if not "." in text and len(text) >= 3:
            text = text[: len(text) - 2] + "." + text[-2:]
        # print(f"OCR PATCH: '{text}'")

        try:
            return float(text)
        except ValueError:
            return 0.0

    def _get_abs_coords(self, coords: tuple[int, int, int, int], size: tuple[int, int]):
        rx1, ry1 = self._ratio(coords[0], coords[1])
        rx2, ry2 = self._ratio(coords[2], coords[3])
        abs_x1, abs_y1 = self._scale_coordinate(rx1, ry1, size)
        abs_x2, abs_y2 = self._scale_coordinate(rx2, ry2, size)
        return abs_x1, abs_y1, abs_x2, abs_y2

    @staticmethod
    def get_ocr_difficulty_text(
        img_crop: Image.Image,
    ) -> Literal["EASY", "HARD", "OVER", "PLUS"]:
        config = "--psm 8 -c tessedit_char_whitelist=EASYHRDOVPLUS"
        return pytesseract.image_to_string(img_crop, config=config)

    @staticmethod
    def get_difficulty(r: int, g: int, b: int) -> str:
        """Identifies difficulty based on RGB color match."""
        target_rgb = (r, g, b)
        for difficulty, color in DIFFICULTY_COLORS.items():
            # Simple tolerance check for each channel
            if all(abs(target_rgb[i] - color[i]) <= COLOR_TOLERANCE for i in range(3)):
                return difficulty
        return "UNKNOWN"

    @staticmethod
    def calculate_judge_rate(ph: int, p: int, g: int, d: int, m: int) -> float:
        """Calculates Judge Rate (Accuracy) percentage."""
        # Total Judge Points = (PH + P) * 100 + Great * 70 + Good * 30 + Miss * 0
        total_judge = (ph + p) * 100 + g * 70 + d * 30
        total_notes = ph + p + g + d + m
        return round(
            total_judge / total_notes, 4
        )  # Returns a percentage (0.0 to 100.0)

    @staticmethod
    def calculate_score(perfect_high: int, perfect: int, great: int):
        return 200 * perfect_high + 150 * perfect + 100 * great

    @staticmethod
    def calculate_rank(judge_rate: float) -> str:
        """Calculates rank based on judge rate."""
        if judge_rate >= 99.8:
            return "SS+"
        elif judge_rate >= 99.5:
            return "SS"
        elif judge_rate >= 99:
            return "S+"
        elif judge_rate >= 98:
            return "S"
        elif judge_rate >= 97:
            return "AA+"
        elif judge_rate >= 95:
            return "AA"
        elif judge_rate >= 90:
            return "A+"
        elif judge_rate >= 80:
            return "A"
        elif judge_rate >= 70:
            return "B"
        else:
            return "C"

    @staticmethod
    def calculate_patch(
        level: int,
        rank: str,
        is_plus: bool,
        judge: float,
    ) -> float:
        """Calculates the P.A.T.C.H. value."""
        rank_ratio = {
            "C": 0.2,
            "B": 0.3,
            "A": 0.4,
            "A+": 0.5,
            "AA": 0.6,
            "AA+": 0.7,
            "S": 0.8,
            "S+": 0.9,
            "SS": 0.95,
            "SS+": 1,
        }

        if rank == "F":
            return 0.0  # Handle case not in rank_ratio

        patch_base = level * 42 * (judge / 100) * rank_ratio[rank]
        if is_plus:
            patch_base *= 1.02

        # The game often rounds this value to two decimal places
        return round(patch_base, 2)

    @staticmethod
    def verify_notes_count(
        total: int, perfect_high: int, perfect: int, great: int, good: int, miss: int
    ):
        if total == perfect_high + perfect + great + good + miss:
            return perfect_high, perfect, great, good, miss
        elif perfect_high > total:
            perfect_high = total - (perfect + great + good + miss)
        elif perfect > total:
            perfect = total - (perfect_high + great + good + miss)
        elif great > total:
            great = total - (perfect_high + perfect + good + miss)
        elif good > total:
            good = total - (perfect_high + perfect + great + miss)
        else:
            miss = total - (perfect_high + perfect + great + good)
        return perfect_high, perfect, great, good, miss

    @staticmethod
    def ocr_preprocess(img: Image.Image, do_invert: bool = False):
        """Do some preprocess (upscaling, binarization) for the best OCR result"""
        resized_img = img.resize(
            (img.width * 4, img.height * 4), Image.Resampling.LANCZOS
        )
        grayscale_img = resized_img.convert("L")
        bw_img = grayscale_img.point(lambda x: 255 if x > 200 else 0, "1")

        if do_invert:
            bw_img = ImageOps.invert(bw_img)

        return bw_img

    @staticmethod
    def find_level_phash(img: Image.Image):
        given_hash = imagehash.phash(img)
        level_hash_map = {
            5: "ec6495db9b249293",
            6: "eea5995a92ad9292",
            8: "eead9552916d9292",
            9: "ec32954d93b2926d",
        }
        closest_level = 0
        closest_distance = float("inf")
        for level, compare_hash in level_hash_map.items():
            compare_hash = imagehash.hex_to_hash(compare_hash)
            distance = compare_hash - given_hash
            if distance < closest_distance:
                closest_distance = distance
                closest_level = level

        return closest_level if closest_distance < 5 else 0

    # --- Main Execution Method ---
    def extract_info(self, image_path: str | None = None) -> AnalysisReport:
        """Main method to analyze a screenshot and return a structured report."""
        try:
            if image_path:
                img = Image.open(image_path)
            else:
                # Try to read image from clipboard
                img = ImageGrab.grabclipboard()
        except FileNotFoundError:
            print(f"Error: File not found at {image_path}")
            return AnalysisReport(song_name="FILE NOT FOUND")
        if img is None:
            print("Error: Clipboard is empty or does not contain an image.")
            # Return an empty report to prevent the crash
            return AnalysisReport(song_name="NO IMAGE")

        screen_type = self.determine_screen_type(img)

        if screen_type == "SELECT":
            return self._analyze_select_screen(img)

        # --- 1. jacket and Song Match ---
        jacket_crop = self._crop_and_ocr(
            img, screen_type, "jacket", lambda x: x, no_preprocess=True
        )  # Pass crop back as PIL Image
        jacket_hash = imagehash.phash(jacket_crop)
        matched_song, match_distance = self.get_best_match_song(jacket_hash)
        if match_distance > 5:
            raise ArchiveException(
                "노래 재킷 인식 실패. 인식할 수 없는 화면이거나 노래가 아직 DB에 등록되지 않았습니다."
            )

        # --- 2. OCR Extraction ---

        lines = self._crop_and_ocr(img, screen_type, "line", self.get_ocr_line)
        level_ocr = self._crop_and_ocr(
            img, screen_type, "level", self.get_ocr_integer, do_invert=True
        )
        patch_ocr = self._crop_and_ocr(
            img, screen_type, "patch", self.get_ocr_patch, do_invert=True
        )
        score_ocr = self._crop_and_ocr(img, screen_type, "score", self.get_ocr_integer)
        total_notes = self._crop_and_ocr(
            img, screen_type, "total_notes", self.get_ocr_integer
        )
        perfect_high = self._crop_and_ocr(
            img, screen_type, "perfect_high_y", self.get_ocr_integer
        )
        perfect = self._crop_and_ocr(
            img, screen_type, "perfect_y", self.get_ocr_integer
        )
        great = self._crop_and_ocr(img, screen_type, "great_y", self.get_ocr_integer)
        good = self._crop_and_ocr(img, screen_type, "good_y", self.get_ocr_integer)
        miss = self._crop_and_ocr(img, screen_type, "miss_y", self.get_ocr_integer)
        rank_crop = self._crop_and_ocr(
            img, screen_type, "rank", lambda x: x, no_preprocess=True
        )
        rank_hash = imagehash.phash(rank_crop)
        perfect_high, perfect, great, good, miss = self.verify_notes_count(
            total_notes, perfect_high, perfect, great, good, miss
        )

        # --- 3. Difficulty Color Check ---
        r, g, b = img.getpixel(
            self._scale_coordinate(
                *self._ratio(*ROI_CONFIG[screen_type]["difficulty_color"]), img.size
            )
        )
        difficulty_str = self.get_difficulty(r, g, b)
        is_plus_difficulty = difficulty_str == "PLUS"

        # --- 4. Calculation ---
        calculated_judge_rate = self.calculate_judge_rate(
            perfect_high, perfect, great, good, miss
        )
        calculated_score = self.calculate_score(perfect_high, perfect, great)
        calculated_rank = self.calculate_rank(calculated_judge_rate)
        # Try to find out if rank is F (bc F cannot be calculated...)
        F_RANK_HASH = imagehash.hex_to_hash("a3636e1f941a1736")
        if F_RANK_HASH - rank_hash < 5:
            calculated_rank = "F"

        level_int = level_ocr
        calculated_patch = self.calculate_patch(
            level_int,
            calculated_rank,
            is_plus_difficulty,
            calculated_judge_rate,
        )
        available_levels = matched_song.get_available_levels(lines, difficulty_str)
        if len(available_levels) == 1:
            level_int = available_levels[0]

        is_full_combo = miss == 0
        is_perfect_decode = calculated_judge_rate == 100
        is_maximum_patch = is_perfect_decode and perfect_high / total_notes >= 0.98

        patch_distance = patch_ocr - calculated_patch
        if -0.1 <= patch_distance <= 0.1:
            calculated_patch = patch_ocr

        # Switch to OCR patch because of bonus patch
        if is_perfect_decode:
            calculated_patch = patch_ocr

        # --- 5. Return Structured Report ---
        return AnalysisReport(
            matched_song,
            calculated_score,
            calculated_judge_rate,
            calculated_patch,
            lines,
            difficulty_str,
            level_int,
            jacket_crop,
            jacket_hash,
            match_distance,
            calculated_rank,
            is_full_combo,
            is_perfect_decode,
            is_maximum_patch,
            total_notes,
            perfect_high,
        )


# --- INITIALIZATION AND EXECUTION ---


def version_to_string(version: tuple[int, int, int]):
    return f"v{version[0]}.{version[1]}.{version[2]}"


def fetch_archive(api_key: str) -> dict[str, DecodeResult]:
    archive_endpoint = "https://www.platina-archive.app/api/v1/get_archive"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    res = requests.post(archive_endpoint, headers=headers)
    archive_json = res.json()
    archive = {}
    for arc in archive_json:
        song_id = arc.get("song_id")
        line = arc.get("line")
        difficulty = arc.get("difficulty")
        level = arc.get("level")
        key = f"{song_id}|{line}|{difficulty}|{level}"
        decoded_at = datetime.fromisoformat(arc.get("decoded_at")).astimezone(
            timezone.utc
        )
        archive[key] = DecodeResult(
            song_id,
            line,
            difficulty,
            level,
            arc.get("judge"),
            arc.get("score"),
            arc.get("patch"),
            decoded_at,
            arc.get("is_full_combo"),
            arc.get("is_max_patch"),
        )
    return archive


def fetch_latest_client_version() -> tuple[int, int, int]:
    """Fetch the latest client version"""
    client_version_endpoint = "https://www.platina-archive.app/api/v1/client_version"
    res = requests.get(client_version_endpoint)
    res.raise_for_status()
    data = res.json()
    return (data["major"], data["minor"], data["patch"])


def fetch_songs():
    """Fetches song and pattern data from the API."""
    songs_endpoint = "https://www.platina-archive.app/api/v1/platina_songs"
    patterns_endpoint = "https://www.platina-archive.app/api/v1/platina_patterns"

    # check local storage
    DEFAULT_DATE = datetime(2025, 4, 10).isoformat()  # Date that needs update
    APPDATA_ROAMING = os.environ.get("APPDATA", os.path.expanduser("~"))
    CACHE_DIR = os.path.join(APPDATA_ROAMING, "PLATiNA-ARCHiVE", "cache")
    CACHED_DB_PATH = os.path.join(CACHE_DIR, "db.json")
    songs_headers = {}
    patterns_headers = {}
    cached_db = {}
    needs_update = False

    if os.path.isfile(CACHED_DB_PATH):
        with open(CACHED_DB_PATH, "r") as f:
            cached_db = json.load(f)
        songs_last_modified = cached_db.get("Songs-Last-Modified", DEFAULT_DATE)
        patterns_last_modified = cached_db.get("Patterns-Last-Modified", DEFAULT_DATE)
        songs_headers = {"If-Modified-Since": songs_last_modified}
        patterns_headers = {"If-Modified-Since": patterns_last_modified}

    # Use POST method and check status
    res_songs = requests.get(songs_endpoint, headers=songs_headers)
    res_patterns = requests.get(patterns_endpoint, headers=patterns_headers)
    res_songs.raise_for_status()
    res_patterns.raise_for_status()

    if res_songs.status_code == 304:
        songs_json = cached_db["songs"]
    else:
        songs_json = res_songs.json()
        new_songs_last_modified = res_songs.headers.get("Last-Modified")
        cached_db["songs"] = songs_json
        cached_db["Songs-Last-Modified"] = new_songs_last_modified
        needs_update = True

    if res_patterns.status_code == 304:
        patterns_json = cached_db["patterns"]
    else:
        patterns_json = res_patterns.json()
        new_patterns_last_modified = res_patterns.headers.get("Last-Modified")
        cached_db["patterns"] = patterns_json
        cached_db["Patterns-Last-Modified"] = new_patterns_last_modified
        needs_update = True

    if needs_update:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHED_DB_PATH, "w") as f:
            json.dump(cached_db, f)

    # Build the Song objects
    songs = {}
    for song_data in songs_json:
        song = Song(
            song_id=song_data.get("songID"),
            title=song_data.get("title"),
            artist=song_data.get("artist", "").strip(),
            bpm=song_data.get("BPM"),
            dlc=song_data.get("DLC"),
            phash=song_data.get("pHash"),
            plus_phash=song_data.get("plusPHash"),
        )
        songs[song.id] = song

    # Link Patterns to Songs
    for pattern_data in patterns_json:
        song_id = pattern_data.get("songID")
        if song_id in songs:
            pattern = Pattern(
                line=pattern_data.get("line"),
                difficulty=pattern_data.get("difficulty"),
                level=pattern_data.get("level"),
                designer=pattern_data.get("designer"),
            )
            songs[song_id].add_pattern(pattern)

    return list(songs.values())


if __name__ == "__main__":
    # 1. Fetch data once at startup
    song_data = None
    while not song_data:
        try:
            song_data = fetch_songs()
        except requests.exceptions.RequestException as e:
            time.sleep(0.5)  # Try again after 0.5s

    # 2. Initialize the analyzer
    analyzer = ScreenshotAnalyzer(song_data)

    # 3. Process screenshots
    ref = os.listdir("example")
    for r in ref:
        print(f"Processing: {r}")
        report = analyzer.extract_info(f"example/{r}")
        print(
            f"{report.song.title} - {report.song.artist} | {report.line}L {report.difficulty} Lv.{report.level}"
        )
        print(f"Judge: {report.judge}")
        print(f"Score: {report.score}")
        print(f"P.A.T.C.H: {report.patch}")
        print("\n\n\n")
