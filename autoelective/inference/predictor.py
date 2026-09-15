"""Inference contract for the exported CNN5/GRU checkpoint 57000."""

import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, UnidentifiedImageError


def _resize_linear(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Half-pixel bilinear resize of float pixels, matching cv2 INTER_LINEAR.

    Pillow's downsampling applies an antialiasing filter, unlike the legacy
    OpenCV path. Keeping this small NumPy implementation avoids shipping OpenCV.
    """
    source_h, source_w = image.shape[:2]
    if (source_w, source_h) == (width, height):
        return image
    x = (np.arange(width, dtype=np.float64) + 0.5) * source_w / width - 0.5
    y = (np.arange(height, dtype=np.float64) + 0.5) * source_h / height - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    ax, ay = (x - x0).astype(np.float32), (y - y0).astype(np.float32)
    x1, y1 = np.clip(x0 + 1, 0, source_w - 1), np.clip(y0 + 1, 0, source_h - 1)
    x0, y0 = np.clip(x0, 0, source_w - 1), np.clip(y0, 0, source_h - 1)
    top = image[y0[:, None], x0] * (1 - ax)[None, :, None] + image[y0[:, None], x1] * ax[None, :, None]
    bottom = image[y1[:, None], x0] * (1 - ax)[None, :, None] + image[y1[:, None], x1] * ax[None, :, None]
    return top * (1 - ay)[:, None, None] + bottom * ay[:, None, None]


def preprocess(image_bytes: bytes) -> np.ndarray:
    """First frame, RGB, white alpha background, float32 resize, W/H swap."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError('验证码图片为空或格式不正确')
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            if source.width * source.height > 4_000_000:
                raise ValueError('验证码图片尺寸异常')
            source.seek(0)
            if source.mode == 'P':
                source = source.convert('RGB')
            if len(source.getbands()) > 3:
                background = Image.new('RGBA', source.size, (255, 255, 255))
                background.paste(source, (0, 0, source.width, source.height), source)
                source = background
            if len(source.getbands()) == 1:
                raise ValueError('验证码图片需要 RGB 彩色通道')
            pixels = np.asarray(source.convert('RGB'), dtype=np.float32)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError('无法读取验证码图片') from error
    resized = _resize_linear(pixels, 130, 52)
    return np.ascontiguousarray((resized.swapaxes(0, 1) / np.float32(255))[None])


def decode_ctc(logits: np.ndarray) -> list:
    """CTC prefix beam search with beam_width=1 and merge_repeated=False.

    Blank is the final logit. Adjacent equal labels are retained only after
    a blank transition. The winning prefix combines blank and label paths;
    replacing this with argmax can change recognition results.
    """
    values = np.asarray(logits, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] < 2 or not np.isfinite(values).all():
        raise ValueError('验证码模型输出无效')
    prefix = []
    blank_probability, label_probability = 0.0, -np.inf
    for row in values:
        maximum = row.max()
        probabilities = row - maximum - np.log(np.exp(row - maximum).sum())
        total = np.logaddexp(blank_probability, label_probability)
        same_label = label_probability + probabilities[prefix[-1]] if prefix else -np.inf
        next_blank = total + probabilities[-1]
        best_total = np.logaddexp(next_blank, same_label)
        winner = None
        winner_probability = -np.inf
        for label in range(len(row) - 1):
            previous = blank_probability if prefix and label == prefix[-1] else total
            candidate = previous + probabilities[label]
            if candidate > best_total:
                best_total, winner, winner_probability = candidate, label, candidate
        if winner is None:
            blank_probability, label_probability = next_blank, same_label
        else:
            prefix.append(winner)
            blank_probability, label_probability = -np.inf, winner_probability
    return prefix


class OnnxPredictor:
    def __init__(self, model_dir: Optional[Path] = None):
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
        self.model_dir = Path(model_dir) if model_dir is not None else root / 'resources' / 'model'
        self._session = None
        self._manifest = None

    def startSession(self):
        if self._session is not None:
            return
        import onnxruntime as ort

        manifest = json.loads((self.model_dir / 'manifest.json').read_text(encoding='utf-8'))
        model_path = self.model_dir / 'captcha.onnx'
        if hashlib.sha256(model_path.read_bytes()).hexdigest() != manifest['sha256']:
            raise ValueError('验证码模型校验失败，请重新解压完整软件包')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=['CPUExecutionProvider'])
        self._manifest = manifest

    def closeSession(self):
        self._session = None

    def predictOneCaptcha(self, image_bytes: bytes) -> str:
        if image_bytes == b'':
            return ''
        batch = preprocess(image_bytes)
        self.startSession()
        logits = self._session.run([self._manifest['output']], {self._manifest['input']: batch})[0]
        indices = decode_ctc(logits[:, 0, :])
        alphabet = self._manifest['alphabet']
        return ''.join(alphabet[index] for index in indices)

    recognize = predictOneCaptcha
