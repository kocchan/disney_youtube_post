"""画像取得モジュール。

ImageProvider 抽象を介して実装を差し替えられる(Strategy パターン)。
- StockImageProvider : フリー素材API(Pexels)。material-collector スキルの恒久登録で使用。
- WebScrapeProvider  : Web検索(DuckDuckGo)スクレイピング。image_dashboard.py の毎回のライブ
                       候補取得と material-collector スキルの両方から使用。著作権は自己責任。

取得した画像は to_vertical() で縦型(1080x1920)にリサイズ＋センタークロップする。
取得失敗時は make_placeholder() の単色画像にフォールバックして全体を止めない。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from config import env

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def to_vertical(src: str | Path, dst: str | Path, width: int = 1080, height: int = 1920) -> Path:
    """画像を縦型(width x height)にリサイズ＋センタークロップして保存する。"""
    src, dst = Path(src), Path(dst)
    img = Image.open(src).convert("RGB")
    target_ratio = width / height
    w, h = img.size
    ratio = w / h
    # アスペクト比を保ったまま、対象枠を覆うようにリサイズ → 中央を切り出す
    if ratio > target_ratio:
        # 横長すぎ: 高さを合わせて横を切る
        new_h = height
        new_w = int(round(height * ratio))
    else:
        # 縦長すぎ: 幅を合わせて縦を切る
        new_w = width
        new_h = int(round(width / ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    img = img.crop((left, top, left + width, top + height))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, quality=90)
    return dst


def make_placeholder(dst: str | Path, text: str = "", width: int = 1080, height: int = 1920) -> Path:
    """取得失敗時の単色プレースホルダ画像を生成する。"""
    dst = Path(dst)
    img = Image.new("RGB", (width, height), (30, 30, 46))
    if text:
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype(str(Path(__file__).parent.parent / "assets/fonts/NotoSansJP-Bold.ttf"), 56)
        except Exception:
            font = ImageFont.load_default()
        draw.text((width // 2, height // 2), text, fill=(200, 200, 220), font=font, anchor="mm")
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, quality=90)
    return dst


class ImageProvider(ABC):
    """画像取得実装の共通インターフェース。"""

    @abstractmethod
    def fetch(self, scene: dict, out_path: str | Path) -> Path:
        """scene の情報から画像を取得し、縦型加工して out_path に保存して返す。"""
        raise NotImplementedError


class StockImageProvider(ImageProvider):
    """Pexels API から画像を取得する(商用利用可)。取得クレジットを self.credits に蓄積する。"""

    def __init__(self, width: int = 1080, height: int = 1920):
        self.api_key = env("PEXELS_API_KEY")
        self.width = width
        self.height = height
        self.credits: list[dict] = []  # 帰属義務用(撮影者・URL)

    def fetch(self, scene: dict, out_path: str | Path) -> Path:
        out_path = Path(out_path)
        query = scene.get("image_query") or scene.get("title") or "background"
        try:
            if not self.api_key:
                raise RuntimeError("PEXELS_API_KEY が未設定")
            raw, credit = self._download(query, out_path.with_suffix(".raw.jpg"))
            result = to_vertical(raw, out_path, self.width, self.height)
            raw.unlink(missing_ok=True)
            credit["scene_id"] = scene.get("id")
            self.credits.append(credit)
            return result
        except Exception as e:  # noqa: BLE001 - 失敗しても止めずフォールバック
            print(f"  [warn] 画像取得失敗(scene {scene.get('id')}): {e} → プレースホルダ使用")
            self.credits.append({"scene_id": scene.get("id"), "source": "placeholder", "note": str(e)})
            return make_placeholder(out_path, text=str(scene.get("id", "")), width=self.width, height=self.height)

    def fetch_candidates(self, scene: dict, out_dir: Path, n: int = 4, suffix: str = "") -> list[dict]:
        """Pexels から n 枚の候補画像を取得して out_dir に保存し、候補リストを返す。"""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        sid = scene.get("id", 0)
        query = scene.get("image_query") or scene.get("title") or "background"
        candidates: list[dict] = []
        if not self.api_key:
            print("  [warn] PEXELS_API_KEY 未設定 — 候補なし")
            return candidates
        try:
            headers = {"Authorization": self.api_key}
            params = {"query": query, "orientation": "portrait", "per_page": n, "size": "large"}
            resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            for i, photo in enumerate(resp.json().get("photos", [])[:n]):
                img_url = photo["src"].get("portrait") or photo["src"]["large"]
                raw = out_dir / f"s{sid:02d}{suffix}_raw{i}.jpg"
                dst = out_dir / f"s{sid:02d}{suffix}_{i}.jpg"
                try:
                    r = requests.get(img_url, timeout=60)
                    r.raise_for_status()
                    raw.write_bytes(r.content)
                    to_vertical(raw, dst, self.width, self.height)
                    raw.unlink(missing_ok=True)
                    candidates.append({
                        "path": str(dst),
                        "query": query,
                        "source": "Pexels",
                        "photographer": photo.get("photographer"),
                        "photographer_url": photo.get("photographer_url"),
                        "photo_url": photo.get("url"),
                    })
                except Exception as e:
                    print(f"    [warn] 候補{i+1} 取得失敗: {e}")
        except Exception as e:
            print(f"  [warn] scene {sid} 候補取得失敗: {e}")
        return candidates

    def _download(self, query: str, raw_path: Path) -> tuple[Path, dict]:
        headers = {"Authorization": self.api_key}
        params = {"query": query, "orientation": "portrait", "per_page": 1, "size": "large"}
        resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            raise RuntimeError(f"検索結果なし: '{query}'")
        photo = photos[0]
        img_url = photo["src"].get("portrait") or photo["src"]["large"]
        img_resp = requests.get(img_url, timeout=60)
        img_resp.raise_for_status()
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(img_resp.content)
        credit = {
            "source": "Pexels",
            "query": query,
            "photographer": photo.get("photographer"),
            "photographer_url": photo.get("photographer_url"),
            "photo_url": photo.get("url"),
        }
        return raw_path, credit


class WebScrapeProvider(ImageProvider):
    """DuckDuckGo 画像検索から画像を取得する(--allow-scrape 時のみ・著作権自己責任)。

    scene に "scrape_query" があればそれを優先し、なければ "image_query" を使う。
    scrape_query には日本語や固有名詞を含む具体的なキーワードを指定できる。
    """

    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://duckduckgo.com/",
    }

    def __init__(self, width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height
        self.credits: list[dict] = []

    def fetch(self, scene: dict, out_path: str | Path) -> Path:
        out_path = Path(out_path)
        query = scene.get("scrape_query") or scene.get("image_query") or scene.get("title", "background")
        try:
            raw, credit = self._download(query, out_path.with_suffix(".raw.jpg"))
            result = to_vertical(raw, out_path, self.width, self.height)
            raw.unlink(missing_ok=True)
            credit["scene_id"] = scene.get("id")
            self.credits.append(credit)
            return result
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] scrape 画像取得失敗(scene {scene.get('id')}): {e} → プレースホルダ使用")
            self.credits.append({"scene_id": scene.get("id"), "source": "placeholder", "note": str(e)})
            return make_placeholder(out_path, text=str(scene.get("id", "")), width=self.width, height=self.height)

    def fetch_candidates(self, scene: dict, out_dir: Path, n: int = 4, suffix: str = "") -> list[dict]:
        """DuckDuckGo から n 枚の候補画像を取得して out_dir に保存し、候補リストを返す。"""
        try:
            from ddgs import DDGS
        except ModuleNotFoundError:
            print("  [warn] ddgs 未インストール → Web候補をスキップ (pip install ddgs で有効化)")
            return []
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        sid = scene.get("id", 0)
        query = scene.get("scrape_query") or scene.get("image_query") or "background"
        candidates: list[dict] = []
        try:
            results = list(DDGS().images(query, max_results=n * 3, type_image="photo", safesearch="strict"))
            for item in results:
                if len(candidates) >= n:
                    break
                img_url = item.get("image")
                if not img_url:
                    continue
                i = len(candidates)
                raw = out_dir / f"s{sid:02d}{suffix}_raw{i}.jpg"
                dst = out_dir / f"s{sid:02d}{suffix}_{i}.jpg"
                try:
                    resp = requests.get(img_url, headers=self._HEADERS, timeout=20)
                    resp.raise_for_status()
                    if "image" not in resp.headers.get("content-type", ""):
                        continue
                    raw.write_bytes(resp.content)
                    to_vertical(raw, dst, self.width, self.height)
                    raw.unlink(missing_ok=True)
                    candidates.append({
                        "path": str(dst),
                        "query": query,
                        "source": "DuckDuckGo/Web",
                        "image_url": img_url,
                        "page_url": item.get("url", ""),
                        "title": (item.get("title") or "")[:80],
                        "note": "著作権は各オリジナル作者に帰属。使用は自己責任。",
                    })
                except Exception:
                    continue
        except Exception as e:
            print(f"  [warn] scene {sid} Web候補取得失敗: {e}")
        return candidates

    def _download(self, query: str, raw_path: Path) -> tuple[Path, dict]:
        from ddgs import DDGS

        results = list(DDGS().images(query, max_results=10, type_image="photo", safesearch="strict"))
        if not results:
            raise RuntimeError(f"検索結果なし: '{query}'")

        for item in results:
            img_url = item.get("image")
            if not img_url:
                continue
            try:
                resp = requests.get(img_url, headers=self._HEADERS, timeout=20)
                resp.raise_for_status()
                if "image" not in resp.headers.get("content-type", ""):
                    continue
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(resp.content)
                credit = {
                    "source": "DuckDuckGo/Web",
                    "query": query,
                    "image_url": img_url,
                    "page_url": item.get("url", ""),
                    "title": (item.get("title") or "")[:80],
                    "note": "著作権は各オリジナル作者に帰属。使用は自己責任。",
                }
                return raw_path, credit
            except Exception:
                continue

        raise RuntimeError(f"ダウンロード可能な画像が見つかりません: '{query}'")
