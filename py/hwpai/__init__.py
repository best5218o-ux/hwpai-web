"""hwpai — HWP·HWPX 를 AI 가 읽을 수 있는 형태(마크다운·표 CSV·RAG 청크)로."""
from .api import read, convert  # noqa: F401

__version__ = "0.9.2"          # 2026-11-27 전달판 2차(0.9.1 + HWP 3.0 원본 독립 판독·검증서, 엔진 C103)
__build__ = "2026-11-27"
