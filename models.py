from __future__ import annotations

from datetime import datetime
from typing import Literal

from imagehash import ImageHash
from PIL import Image


class ArchiveException(Exception):
    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self):
        return f"Error: {self.msg}"


class DecodeResult:
    def __init__(
        self,
        song_id: int,
        line: Literal[4, 6],
        difficulty: Literal["EASY", "HARD", "OVER", "PLUS"],
        level: int,
        judge: float,
        score: int,
        patch: float,
        decoded_at: datetime,
        is_full_combo: bool,
        is_max_patch: bool,
    ):
        self._song_id = song_id
        self._line = line
        self._difficulty = difficulty
        self._level = level
        self._judge = judge
        self._score = score
        self._patch = patch
        self._decoded_at = decoded_at
        self._is_full_combo = is_full_combo
        self._is_max_patch = is_max_patch

    @property
    def song_id(self):
        return self._song_id

    @property
    def line(self):
        return self._line

    @property
    def difficulty(self):
        return self._difficulty

    @property
    def level(self):
        return self._level

    @property
    def judge(self):
        return self._judge

    @judge.setter
    def judge(self, new_judge: float):
        self._judge = new_judge

    @property
    def score(self):
        return self._score

    @score.setter
    def score(self, new_score: int):
        self._score = new_score

    @property
    def patch(self):
        return self._patch

    @patch.setter
    def patch(self, new_patch: float):
        self._patch = new_patch

    @property
    def decoded_at(self):
        return self._decoded_at

    @decoded_at.setter
    def decoded_at(self, new_decoded_at: datetime):
        self._decoded_at = new_decoded_at

    @property
    def is_full_combo(self):
        return self._is_full_combo

    @is_full_combo.setter
    def is_full_combo(self, new_is_full_combo: bool):
        self._is_full_combo = new_is_full_combo

    @property
    def is_max_patch(self):
        return self._is_max_patch

    @is_max_patch.setter
    def is_max_patch(self, new_is_max_patch: bool):
        self._is_max_patch = new_is_max_patch


class AnalysisReport:
    def __init__(
        self,
        song: Song,
        score: int,
        judge: float,
        patch: float,
        line: Literal[4, 6],
        difficulty: Literal["EASY", "HARD", "OVER", "PLUS"],
        level: int,
        jacket_image: Image.Image,
        jacket_hash: ImageHash,
        match_distance,
        rank: str,
        is_full_combo: bool,
        is_perfect_decode: bool,
        is_maximum_patch: bool,
        total_notes: int = 0,
        perfect_high: int = 0,
    ):
        self._song = song
        self._score = score
        self._judge = judge
        self._patch = patch
        self._line = line
        self._difficulty = difficulty
        self._level = level
        self._jacket_image = jacket_image
        self._jacket_hash = jacket_hash
        self._match_distance = match_distance
        self._rank = rank
        self._is_full_combo = is_full_combo
        self._is_perfect_decode = is_perfect_decode
        self._is_maximum_patch = is_maximum_patch
        self._total_notes = total_notes
        self._perfect_high = perfect_high

    def __str__(self):
        return f"{self.song.title} - {self.song.artist} | {self.line}L {self.difficulty} Lv.{self.level}\nJudge: {self.judge}%\nScore: {self.score}\nP.A.T.C.H.: {self.patch}"

    def json(self):
        return {
            "song_id": self.song.id,
            "line": self.line,
            "difficulty": self.difficulty,
            "level": self.level,
            "judge": self.judge,
            "score": self.score,
            "patch": self.patch,
            "is_full_combo": self.is_full_combo,
            "is_max_patch": self.is_maximum_patch,
        }

    @property
    def song(self):
        return self._song

    @property
    def score(self):
        return self._score

    @property
    def judge(self):
        return self._judge

    @property
    def patch(self):
        return self._patch

    @property
    def line(self):
        return self._line

    @property
    def difficulty(self):
        return self._difficulty

    @property
    def level(self):
        return self._level

    @property
    def jacket_image(self):
        return self._jacket_image

    @property
    def jacket_hash(self):
        return self._jacket_hash

    @property
    def match_distance(self):
        return self._match_distance

    @property
    def rank(self):
        return self._rank

    @property
    def is_full_combo(self):
        return self._is_full_combo

    @property
    def is_perfect_decode(self):
        return self._is_perfect_decode

    @property
    def is_maximum_patch(self):
        return self._is_maximum_patch

    @property
    def total_notes(self):
        return self._total_notes

    @property
    def perfect_high(self):
        return self._perfect_high


class Pattern:
    def __init__(
        self,
        line: Literal[4, 6],
        difficulty: Literal["EASY", "HARD", "OVER", "PLUS"],
        level: int,
        designer: str,
    ):
        self._line = line
        self._difficulty = difficulty
        self._level = level
        self._designer = designer

    @property
    def line(self):
        return self._line

    @property
    def difficulty(self):
        return self._difficulty

    @property
    def level(self):
        return self._level

    @property
    def designer(self):
        return self._designer

    def __str__(self):
        return f"{self.line}L {self.difficulty} Lv.{self.level} by {self.designer}"


class Song:
    def __init__(
        self,
        song_id: int,
        title: str,
        artist: str,
        bpm: str,
        dlc: str,
        phash: str | None,
        plus_phash: str | None,
    ):
        self._id = song_id
        self._title = title
        self._artist = artist
        self._bpm = bpm
        self._dlc = dlc
        self._phash = phash
        self._plus_phash = plus_phash
        self._patterns: list[Pattern] = []

    @property
    def id(self):
        return self._id

    @property
    def title(self):
        return self._title

    @property
    def artist(self):
        return self._artist

    @property
    def bpm(self):
        return self._bpm

    @property
    def dlc(self):
        return self._dlc

    @property
    def phash(self):
        return self._phash

    @property
    def plus_phash(self):
        return self._plus_phash

    @property
    def patterns(self):
        return self._patterns

    def add_pattern(self, pattern: Pattern):
        self._patterns.append(pattern)

    def get_available_levels(
        self, line: Literal[4, 6], difficulty: Literal["EASY", "HARD", "OVER", "PLUS"]
    ) -> list[int]:
        levels = []
        for pattern in self._patterns:
            if pattern.line == line and pattern.difficulty == difficulty:
                levels.append(pattern.level)
        return levels


if __name__ == "__main__":
    pass
